"""Integration tests for model-ready training-dataset materialization."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from pit_feature_store.feature_registry import load_feature_registry
from pit_feature_store.training_dataset import (
    TrainingDatasetConfig,
    TrainingDatasetError,
    build_training_dataset,
)

ROOT = Path(__file__).resolve().parents[2]
PRIMARY = ROOT / "configs/features/transaction_velocity_v1.yaml"
SECONDARY = ROOT / "configs/features/transaction_velocity_card_v1.yaml"


def _split_config(path: Path) -> None:
    path.write_text(
        """version: 1
name: test_temporal_split_v1
source_split: train
time_column: TransactionDT
observation_id: TransactionID
label_column: isFraud
strategy: fixed_transaction_dt_boundaries
boundary_policy: start_inclusive_end_exclusive
boundary_alignment_seconds: 20
target_proportions:
  train: 0.6
  validation: 0.2
  internal_test: 0.2
boundaries:
  validation_start_transaction_dt: 40
  internal_test_start_transaction_dt: 60
synthetic_event_time_reference:
  validation_start: synthetic
  internal_test_start: synthetic
""",
        encoding="utf-8",
    )


def _preprocessing_artifact(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "artifact_type": "preprocessing_contract",
                "name": "test_preprocessor_v1",
                "version": 1,
                "fit_policy": {
                    "model_split": "train",
                    "transaction_dt_start_inclusive": 10,
                    "transaction_dt_end_exclusive": 40,
                    "observed_max_transaction_dt": 30,
                    "fit_row_count": 3,
                },
                "numeric_features": {
                    "TransactionAmt": {
                        "strategy": "median",
                        "fill_value": 2.0,
                        "train_null_count": 1,
                    }
                },
                "categorical_features": {
                    "ProductCD": {
                        "min_frequency": 2,
                        "categories": ["__MISSING__", "__UNKNOWN__", "A"],
                        "retained_category_count": 1,
                    }
                },
                "missing_category_token": "__MISSING__",
                "unknown_category_token": "__UNKNOWN__",
                "semantic_sha256": "test-preprocessing-hash",
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _sources(tmp_path: Path, *, omit_offline_id: int | None = None) -> tuple[Path, Path]:
    silver = tmp_path / "silver.parquet"
    offline = tmp_path / "offline.parquet"
    connection = duckdb.connect()
    connection.execute(
        f"""
        COPY (
            SELECT * FROM (VALUES
                (1, 10, TIMESTAMPTZ '2017-01-01 00:00:10+00', 0, 1.0, 'A'),
                (2, 20, TIMESTAMPTZ '2017-01-01 00:00:20+00', 1, 3.0, 'A'),
                (3, 30, TIMESTAMPTZ '2017-01-01 00:00:30+00', 0, NULL, NULL),
                (4, 40, TIMESTAMPTZ '2017-01-01 00:00:40+00', 0, 999.0, 'FUTURE'),
                (5, 50, TIMESTAMPTZ '2017-01-01 00:00:50+00', 1, 999.0, 'FUTURE'),
                (6, 60, TIMESTAMPTZ '2017-01-01 00:01:00+00', 0, 5000.0, 'TEST')
            ) AS rows(TransactionID, TransactionDT, event_time, isFraud,
                      TransactionAmt, ProductCD)
        ) TO '{silver.as_posix()}' (FORMAT PARQUET)
        """
    )
    primary = load_feature_registry(PRIMARY)
    secondary = load_feature_registry(SECONDARY)
    feature_map = {
        f"{registry.feature_set.output_prefix}{feature.name}": feature.aggregation
        for registry in (primary, secondary)
        for feature in registry.features
    }
    expressions = []
    for column, aggregation in feature_map.items():
        if aggregation in {"avg", "max", "time_since_previous"}:
            expressions.append(
                f"CASE WHEN TransactionID = 1 THEN 1.0 "
                f"WHEN TransactionID = 2 THEN 3.0 "
                f"WHEN TransactionID = 3 THEN NULL "
                f'ELSE 999.0 END AS "{column}"'
            )
        else:
            expressions.append(f'CASE WHEN TransactionID = 3 THEN NULL ELSE 1 END AS "{column}"')
    where = "" if omit_offline_id is None else f"WHERE TransactionID != {omit_offline_id}"
    connection.execute(
        f"""
        COPY (
            SELECT TransactionID, event_time, {", ".join(expressions)},
                   1::INTEGER AS feature_table_version
            FROM read_parquet('{silver.as_posix()}')
            {where}
        ) TO '{offline.as_posix()}' (FORMAT PARQUET)
        """
    )
    connection.close()
    return silver, offline


def _config(tmp_path: Path, silver: Path, offline: Path) -> TrainingDatasetConfig:
    split = tmp_path / "split.yaml"
    artifact = tmp_path / "preprocessor.json"
    _split_config(split)
    _preprocessing_artifact(artifact)
    return TrainingDatasetConfig.model_validate(
        {
            "version": 1,
            "name": "test_training_dataset_v1",
            "silver_source_glob": silver,
            "offline_feature_glob": offline,
            "offline_feature_table_version": 1,
            "temporal_split_config": split,
            "preprocessing_artifact": artifact,
            "primary_feature_registry": PRIMARY,
            "secondary_feature_registry": SECONDARY,
            "output_root": tmp_path / "training",
            "partition_column": "model_split",
            "pit_null_policy": {
                "zero_default_aggregations": ["count", "sum", "count_distinct"],
                "train_median_aggregations": ["avg", "max", "time_since_previous"],
                "add_missing_indicators": True,
            },
        }
    )


def test_builds_model_ready_dataset_without_future_preprocessing_leakage(
    tmp_path: Path,
) -> None:
    silver, offline = _sources(tmp_path)
    config = _config(tmp_path, silver, offline)

    manifest = build_training_dataset(config)

    output = tmp_path / "training" / "v1"
    output_glob = (output / "model_split=*" / "*.parquet").as_posix()
    connection = duckdb.connect()
    quality = connection.execute(
        f"""
        SELECT COUNT(*), COUNT(DISTINCT TransactionID),
               COUNT(*) FILTER (WHERE ProductCD = '__UNKNOWN__')
        FROM read_parquet('{output_glob}', hive_partitioning=true)
        """
    ).fetchone()
    row3 = connection.execute(
        f"""
        SELECT TransactionAmt, ProductCD, card_amount_avg_24h,
               card_amount_avg_24h__missing, card_txn_count_24h,
               card_txn_count_24h__missing
        FROM read_parquet('{output_glob}', hive_partitioning=true)
        WHERE TransactionID = 3
        """
    ).fetchone()
    split_counts = dict(
        connection.execute(
            f"""
            SELECT model_split, COUNT(*)
            FROM read_parquet('{output_glob}', hive_partitioning=true)
            GROUP BY model_split
            """
        ).fetchall()
    )
    connection.close()

    assert quality == (6, 6, 3)
    assert row3 == (2.0, "__MISSING__", 2.0, 1, 0, 1)
    assert split_counts == {"train": 3, "validation": 2, "internal_test": 1}
    assert manifest["quality"]["missing_offline_feature_rows"] == 0
    assert manifest["quality"]["null_model_feature_values"] == 0
    assert manifest["features"]["raw_feature_count"] == 2
    assert manifest["features"]["pit_feature_count"] == 20
    assert manifest["features"]["model_feature_count"] == 42
    assert len(list((output / "manifests").glob("*.json"))) == 1


def test_missing_offline_feature_row_fails_before_publish(tmp_path: Path) -> None:
    silver, offline = _sources(tmp_path, omit_offline_id=6)
    config = _config(tmp_path, silver, offline)

    with pytest.raises(TrainingDatasetError, match="missing_features=1"):
        build_training_dataset(config)

    assert not (tmp_path / "training" / "v1").exists()
    assert not list((tmp_path / "training").glob(".staging_*"))
