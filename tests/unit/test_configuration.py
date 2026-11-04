from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from pit_feature_store.configuration import ProjectConfig, load_pipeline_config


def test_repository_pipeline_config_is_valid() -> None:
    project_root = Path(__file__).resolve().parents[2]

    config = load_pipeline_config(project_root)

    assert config.project_config.project.synthetic_epoch == datetime(2017, 1, 1, tzinfo=UTC)
    assert config.project_config.project.timezone == "UTC"
    assert config.project_config.processing.transaction_time_offset_column == "TransactionDT"
    assert config.project_config.processing.transaction_time_offset_unit == "seconds"
    assert config.source_path("train_transaction") == (
        project_root / "data/raw/train_transaction.csv"
    )
    assert config.storage_path("bronze") == project_root / "data/bronze"


def test_all_four_source_roles_are_defined() -> None:
    project_root = Path(__file__).resolve().parents[2]
    config = load_pipeline_config(project_root)

    actual = {(source.split, source.table) for source in config.sources_config.sources.values()}

    assert actual == {
        ("train", "transaction"),
        ("train", "identity"),
        ("test", "transaction"),
        ("test", "identity"),
    }


def test_synthetic_epoch_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError, match="synthetic_epoch must include a timezone"):
        ProjectConfig.model_validate(
            {
                "project": {
                    "name": "test",
                    "environment": "test",
                    "timezone": "UTC",
                    "synthetic_epoch": "2017-01-01T00:00:00",
                },
                "storage": {
                    "raw": "data/raw",
                    "bronze": "data/bronze",
                    "silver": "data/silver",
                    "offline_store": "data/offline_store",
                },
                "processing": {
                    "transaction_time_offset_column": "TransactionDT",
                    "transaction_time_offset_unit": "seconds",
                    "observation_time_column": "event_time",
                    "transaction_id_column": "TransactionID",
                    "target_column": "isFraud",
                },
            }
        )
