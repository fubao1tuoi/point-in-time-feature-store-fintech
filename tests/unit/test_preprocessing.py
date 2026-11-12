"""Tests proving preprocessing statistics are fitted on temporal train only."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest
from pydantic import ValidationError

from pit_feature_store.preprocessing import (
    PreprocessingConfig,
    fit_preprocessor,
)


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


def _preprocessing_config() -> PreprocessingConfig:
    return PreprocessingConfig.model_validate(
        {
            "version": 1,
            "name": "test_preprocessor_v1",
            "fit_split": "train",
            "fit_time_column": "TransactionDT",
            "numeric_imputation": "median",
            "categorical_encoding": "fixed_vocabulary",
            "categorical_min_frequency": 2,
            "missing_category_token": "__MISSING__",
            "unknown_category_token": "__UNKNOWN__",
            "numeric_features": ["TransactionAmt"],
            "categorical_features": ["ProductCD"],
        }
    )


def _source(path: Path) -> None:
    connection = duckdb.connect()
    connection.execute(
        f"""
        COPY (
            SELECT * FROM (VALUES
                (1, 10, 1.0, 'A'),
                (2, 20, 3.0, 'A'),
                (3, 30, NULL, 'RARE_TRAIN'),
                (4, 40, 999.0, 'VALIDATION_ONLY'),
                (5, 50, 999.0, 'VALIDATION_ONLY'),
                (6, 60, 5000.0, 'TEST_ONLY')
            ) AS rows(TransactionID, TransactionDT, TransactionAmt, ProductCD)
        ) TO '{path.as_posix()}' (FORMAT PARQUET)
        """
    )
    connection.close()


def test_fit_uses_only_train_median_and_train_category_vocabulary(tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    split_config = tmp_path / "split.yaml"
    artifact_path = tmp_path / "preprocessor.json"
    report_path = tmp_path / "report.json"
    _source(source)
    _split_config(split_config)

    artifact, report = fit_preprocessor(
        source,
        _preprocessing_config(),
        split_config,
        artifact_path,
        report_path,
    )

    assert artifact_path.is_file()
    assert report_path.is_file()
    assert artifact["fit_policy"]["fit_row_count"] == 3
    assert artifact["fit_policy"]["observed_max_transaction_dt"] == 30
    assert artifact["numeric_features"]["TransactionAmt"]["fill_value"] == 2.0
    assert artifact["categorical_features"]["ProductCD"]["categories"] == [
        "__MISSING__",
        "__UNKNOWN__",
        "A",
    ]
    assert "VALIDATION_ONLY" not in artifact["categorical_features"]["ProductCD"]["categories"]
    assert report["validation_or_test_rows_used_for_fit"] == 0
    assert report["splits"]["validation"]["unknown_non_null_category_counts"]["ProductCD"] == 2


def test_semantic_fingerprint_is_stable_across_refits(tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    split_config = tmp_path / "split.yaml"
    _source(source)
    _split_config(split_config)

    first, _ = fit_preprocessor(
        source,
        _preprocessing_config(),
        split_config,
        tmp_path / "first.json",
        tmp_path / "first_report.json",
    )
    second, _ = fit_preprocessor(
        source,
        _preprocessing_config(),
        split_config,
        tmp_path / "second.json",
        tmp_path / "second_report.json",
    )

    assert first["fitted_at_utc"] != second["fitted_at_utc"]
    assert first["semantic_sha256"] == second["semantic_sha256"]


def test_numeric_and_categorical_feature_overlap_is_rejected() -> None:
    content = _preprocessing_config().model_dump()
    content["categorical_features"].append("TransactionAmt")

    with pytest.raises(ValidationError, match="must not overlap"):
        PreprocessingConfig.model_validate(content)
