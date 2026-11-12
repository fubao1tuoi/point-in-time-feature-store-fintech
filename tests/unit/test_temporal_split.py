"""Tests for chronological train/validation/internal-test policy."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest
from pydantic import ValidationError

from pit_feature_store.temporal_split import (
    TemporalSplitConfig,
    audit_temporal_split,
    load_temporal_split_config,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/training_split.yaml"


def test_fixed_boundaries_assign_ties_to_later_split() -> None:
    config = load_temporal_split_config(CONFIG)
    validation = config.boundaries.validation_start_transaction_dt
    internal_test = config.boundaries.internal_test_start_transaction_dt

    assert config.split_name(validation - 1) == "train"
    assert config.split_name(validation) == "validation"
    assert config.split_name(internal_test - 1) == "validation"
    assert config.split_name(internal_test) == "internal_test"


def test_invalid_or_non_contiguous_boundary_order_is_rejected() -> None:
    content = load_temporal_split_config(CONFIG).model_dump()
    content["boundaries"] = {
        "validation_start_transaction_dt": 200,
        "internal_test_start_transaction_dt": 100,
    }

    with pytest.raises(ValidationError, match="validation boundary must be earlier"):
        TemporalSplitConfig.model_validate(content)


def test_audit_reconciles_rows_labels_and_temporal_order(tmp_path: Path) -> None:
    source = tmp_path / "train.parquet"
    report_path = tmp_path / "temporal_split_report.json"
    connection = duckdb.connect()
    connection.execute(
        f"""
        COPY (
            SELECT * FROM (VALUES
                (1, 10, 0), (2, 20, 1), (3, 30, 0),
                (4, 40, 0), (5, 50, 1), (6, 60, 0),
                (7, 70, 1), (8, 80, 0), (9, 90, 1)
            ) AS rows(TransactionID, TransactionDT, isFraud)
        ) TO '{source.as_posix()}' (FORMAT PARQUET)
        """
    )
    connection.close()
    config = TemporalSplitConfig.model_validate(
        {
            "version": 1,
            "name": "test_split_v1",
            "source_split": "train",
            "time_column": "TransactionDT",
            "observation_id": "TransactionID",
            "label_column": "isFraud",
            "strategy": "fixed_transaction_dt_boundaries",
            "boundary_policy": "start_inclusive_end_exclusive",
            "boundary_alignment_seconds": 10,
            "target_proportions": {
                "train": 0.6,
                "validation": 0.2,
                "internal_test": 0.2,
            },
            "boundaries": {
                "validation_start_transaction_dt": 40,
                "internal_test_start_transaction_dt": 70,
            },
            "synthetic_event_time_reference": {
                "validation_start": "synthetic",
                "internal_test_start": "synthetic",
            },
        }
    )

    report = audit_temporal_split(source, config, report_path)

    assert report_path.is_file()
    assert report["total_rows"] == 9
    assert report["quality"]["temporal_overlap"] is False
    assert report["splits"]["train"]["row_count"] == 3
    assert report["splits"]["validation"]["row_count"] == 3
    assert report["splits"]["internal_test"]["row_count"] == 3
    assert report["splits"]["train"]["max_transaction_dt"] == 30
    assert report["splits"]["validation"]["min_transaction_dt"] == 40
    assert report["splits"]["internal_test"]["min_transaction_dt"] == 70


def test_project_boundaries_align_to_utc_midnight() -> None:
    config = load_temporal_split_config(CONFIG)

    assert config.boundary_alignment_seconds == 86400
    assert config.boundaries.validation_start_transaction_dt % 86400 == 0
    assert config.boundaries.internal_test_start_transaction_dt % 86400 == 0
