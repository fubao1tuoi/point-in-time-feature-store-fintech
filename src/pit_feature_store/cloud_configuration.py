"""Validated, environment-aware configuration for Google Cloud deployment."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from pit_feature_store.structured_logging import emit_structured_log

DEFAULT_CLOUD_CONFIG = Path("configs/cloud/dev.yaml")
ENV_PATTERN = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
PROJECT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
REGION_PATTERN = re.compile(r"^[a-z]+-[a-z]+[0-9]+$")
BUCKET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$")
RESOURCE_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,61}[a-z0-9]$")
DATASET_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,1023}$")
LABEL_VALUE_PATTERN = re.compile(r"^[a-z0-9_-]{1,63}$")


class CloudConfigurationError(ValueError):
    """Raised when cloud configuration cannot be expanded or validated."""


class GcpConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    region: str
    data_bucket: str
    artifact_registry_repository: str
    bigquery_dataset: str

    @model_validator(mode="after")
    def validate_names(self) -> GcpConfig:
        if not PROJECT_ID_PATTERN.fullmatch(self.project_id):
            raise ValueError("gcp.project_id is not a valid Google Cloud project ID")
        if not REGION_PATTERN.fullmatch(self.region):
            raise ValueError("gcp.region must look like asia-southeast1")
        if self.data_bucket.startswith("gs://") or not BUCKET_PATTERN.fullmatch(
            self.data_bucket
        ):
            raise ValueError("gcp.data_bucket must be a bucket name without gs://")
        if not RESOURCE_PATTERN.fullmatch(self.artifact_registry_repository):
            raise ValueError("invalid Artifact Registry repository name")
        if not DATASET_PATTERN.fullmatch(self.bigquery_dataset):
            raise ValueError("invalid BigQuery dataset name")
        return self


class JobNames(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ingest: str
    features: str
    score: str


class NamingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_prefix: str
    image_name: str
    jobs: JobNames
    workflow: str
    scheduler: str

    @model_validator(mode="after")
    def validate_resource_names(self) -> NamingConfig:
        values = [
            self.resource_prefix,
            self.image_name,
            self.jobs.ingest,
            self.jobs.features,
            self.jobs.score,
            self.workflow,
            self.scheduler,
        ]
        invalid = [value for value in values if not RESOURCE_PATTERN.fullmatch(value)]
        if invalid:
            raise ValueError(f"invalid cloud resource names: {invalid}")
        return self


class RuntimePaths(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # These are paths inside a Linux Cloud Run container. PurePosixPath keeps
    # their representation stable even when validation runs on Windows.
    data_root: PurePosixPath
    raw_root: PurePosixPath
    bronze_root: PurePosixPath
    silver_root: PurePosixPath
    offline_store_root: PurePosixPath
    training_root: PurePosixPath
    artifacts_root: PurePosixPath
    models_root: PurePosixPath
    reports_root: PurePosixPath
    manifests_root: PurePosixPath
    catalog_root: PurePosixPath

    @model_validator(mode="after")
    def validate_cloud_paths(self) -> RuntimePaths:
        root = self.data_root
        if not root.is_absolute():
            raise ValueError("runtime_paths.data_root must be an absolute container path")
        for field_name in type(self).model_fields:
            value = getattr(self, field_name)
            if not value.is_absolute():
                raise ValueError(f"runtime_paths.{field_name} must be absolute")
            if value != root and root not in value.parents:
                raise ValueError(f"runtime_paths.{field_name} must be inside data_root")
        return self

    def for_layer(self, layer: str) -> PurePosixPath:
        field_name = f"{layer}_root" if layer != "data" else "data_root"
        if field_name not in type(self).model_fields:
            raise KeyError(f"unknown runtime path layer: {layer}")
        return getattr(self, field_name)


class StoragePrefixes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw: str
    bronze: str
    silver: str
    offline_store: str
    training: str
    artifacts: str
    models: str
    reports: str
    manifests: str
    catalog: str

    @model_validator(mode="after")
    def validate_prefixes(self) -> StoragePrefixes:
        values = [getattr(self, name) for name in type(self).model_fields]
        if len(values) != len(set(values)):
            raise ValueError("storage prefixes must be unique")
        invalid = [
            value
            for value in values
            if value.startswith("/") or value.endswith("/") or ".." in value.split("/")
        ]
        if invalid:
            raise ValueError(f"storage prefixes must be relative and normalized: {invalid}")
        return self


class ExecutionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: Literal["UTC"]
    default_feature_version: int = Field(ge=1)
    default_model_version: int = Field(ge=1)
    default_task_count: int = Field(ge=1, le=10000)
    default_max_retries: int = Field(ge=0, le=10)
    structured_logging: Literal[True]


class CloudConfig(BaseModel):
    """Complete non-secret contract for one Google Cloud environment."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    environment: Literal["dev", "staging", "prod"]
    gcp: GcpConfig
    naming: NamingConfig
    runtime_paths: RuntimePaths
    storage_prefixes: StoragePrefixes
    execution: ExecutionConfig
    labels: dict[str, str]

    @model_validator(mode="after")
    def validate_labels(self) -> CloudConfig:
        invalid = {
            key: value
            for key, value in self.labels.items()
            if not LABEL_VALUE_PATTERN.fullmatch(key)
            or not LABEL_VALUE_PATTERN.fullmatch(value)
        }
        if invalid:
            raise ValueError(f"invalid lowercase GCP labels: {invalid}")
        if self.labels.get("environment") != self.environment:
            raise ValueError("labels.environment must match environment")
        return self

    @property
    def bucket_uri(self) -> str:
        return f"gs://{self.gcp.data_bucket}"

    def storage_uri(self, layer: str) -> str:
        if layer not in type(self.storage_prefixes).model_fields:
            raise KeyError(f"unknown storage layer: {layer}")
        return f"{self.bucket_uri}/{getattr(self.storage_prefixes, layer)}"


def _expand_environment(value: object, environment: Mapping[str, str]) -> object:
    if isinstance(value, dict):
        return {key: _expand_environment(item, environment) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_environment(item, environment) for item in value]
    if not isinstance(value, str):
        return value

    missing: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        resolved = environment.get(name)
        if not resolved:
            missing.add(name)
            return match.group(0)
        return resolved

    expanded = ENV_PATTERN.sub(replace, value)
    if missing:
        names = ", ".join(sorted(missing))
        raise CloudConfigurationError(f"missing required environment variables: {names}")
    return expanded


def load_cloud_config(
    path: Path = DEFAULT_CLOUD_CONFIG,
    *,
    environment: Mapping[str, str] | None = None,
) -> CloudConfig:
    """Expand environment placeholders and validate a non-secret cloud config."""
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(content, dict):
        raise CloudConfigurationError(f"expected YAML mapping in {path}")
    expanded = _expand_environment(content, environment or os.environ)
    return CloudConfig.model_validate(expanded)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CLOUD_CONFIG)
    parser.add_argument(
        "--show-effective",
        action="store_true",
        help="Print the validated non-secret effective configuration",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_cloud_config(args.config)
    except Exception as exc:
        emit_structured_log(
            run_id="cloud-config-validation",
            stage="cloud_config",
            status="failed",
            environment="dev",
            message=str(exc),
        )
        raise

    emit_structured_log(
        run_id="cloud-config-validation",
        stage="cloud_config",
        status="success",
        environment=config.environment,
        version=config.version,
        message="cloud configuration is valid",
        extra={
            "project_id": config.gcp.project_id,
            "region": config.gcp.region,
            "bucket_uri": config.bucket_uri,
        },
    )
    if args.show_effective:
        print(json.dumps(config.model_dump(mode="json"), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
