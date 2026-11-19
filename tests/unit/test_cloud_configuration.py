"""Tests for environment expansion, naming and runtime paths in cloud config."""

from pathlib import Path, PurePosixPath

import pytest

from pit_feature_store.cloud_configuration import CloudConfigurationError, load_cloud_config

CONFIG = Path("configs/cloud/dev.yaml")
VALID_ENV = {
    "GCP_PROJECT_ID": "pit-feature-store-dev-12345",
    "GCP_REGION": "asia-southeast1",
    "GCP_DATA_BUCKET": "pit-feature-store-dev-12345-data",
    "PIT_DATA_ROOT": "/mnt/pit-data",
}


def test_repository_cloud_config_expands_and_validates() -> None:
    config = load_cloud_config(CONFIG, environment=VALID_ENV)

    assert config.gcp.project_id == "pit-feature-store-dev-12345"
    assert config.gcp.region == "asia-southeast1"
    assert config.bucket_uri == "gs://pit-feature-store-dev-12345-data"
    assert config.runtime_paths.for_layer("silver") == PurePosixPath(
        "/mnt/pit-data/silver"
    )
    assert config.runtime_paths.model_dump(mode="json")["data_root"] == "/mnt/pit-data"
    assert config.storage_uri("offline_store").endswith("/offline")
    assert config.execution.timezone == "UTC"


def test_cloud_config_reports_missing_environment_variable() -> None:
    incomplete = {key: value for key, value in VALID_ENV.items() if key != "GCP_PROJECT_ID"}

    with pytest.raises(CloudConfigurationError, match="GCP_PROJECT_ID"):
        load_cloud_config(CONFIG, environment=incomplete)


def test_runtime_paths_must_stay_inside_mount_root() -> None:
    invalid = {**VALID_ENV, "PIT_DATA_ROOT": "relative/path"}

    with pytest.raises(ValueError, match="must be an absolute container path"):
        load_cloud_config(CONFIG, environment=invalid)
