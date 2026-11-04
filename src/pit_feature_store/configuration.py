"""Validated YAML configuration shared by ingestion and Silver pipelines."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SourceDefinition(BaseModel):
    """Contract for one immutable IEEE-CIS raw source."""

    model_config = ConfigDict(extra="forbid")

    path: Path
    file_format: Literal["csv"]
    split: Literal["train", "test"]
    table: Literal["transaction", "identity"]
    bronze_output: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    primary_key: str | None = None
    join_key: str | None = None
    optional: bool = False
    required_columns: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_table_key(self) -> SourceDefinition:
        if self.table == "transaction" and self.primary_key is None:
            raise ValueError("transaction source requires primary_key")
        if self.table == "identity" and self.join_key is None:
            raise ValueError("identity source requires join_key")
        key = self.primary_key if self.table == "transaction" else self.join_key
        if key not in self.required_columns:
            raise ValueError(f"key '{key}' must be included in required_columns")
        return self


class SourcesConfig(BaseModel):
    """Versioned collection of raw source definitions."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    sources: dict[str, SourceDefinition]

    @model_validator(mode="after")
    def validate_source_matrix(self) -> SourcesConfig:
        combinations = {(source.split, source.table) for source in self.sources.values()}
        expected = {
            ("train", "transaction"),
            ("train", "identity"),
            ("test", "transaction"),
            ("test", "identity"),
        }
        if combinations != expected:
            raise ValueError("sources must define one train/test transaction/identity matrix")
        outputs = [source.bronze_output for source in self.sources.values()]
        if len(outputs) != len(set(outputs)):
            raise ValueError("bronze_output values must be unique")
        return self


class ProjectDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    environment: str
    timezone: Literal["UTC"]
    synthetic_epoch: datetime

    @model_validator(mode="after")
    def validate_epoch(self) -> ProjectDefinition:
        if self.synthetic_epoch.tzinfo is None:
            raise ValueError("synthetic_epoch must include a timezone")
        if self.synthetic_epoch.utcoffset() != UTC.utcoffset(self.synthetic_epoch):
            raise ValueError("synthetic_epoch must use UTC")
        return self


class StorageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw: Path
    bronze: Path
    silver: Path
    offline_store: Path


class ProcessingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_time_offset_column: str
    transaction_time_offset_unit: Literal["seconds"]
    observation_time_column: str
    transaction_id_column: str
    target_column: str


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: ProjectDefinition
    storage: StorageConfig
    processing: ProcessingConfig


class PipelineConfig(BaseModel):
    """Validated project and source configuration with path resolution helpers."""

    project_root: Path
    project_config: ProjectConfig
    sources_config: SourcesConfig

    def source_path(self, source_name: str) -> Path:
        path = self.sources_config.sources[source_name].path
        return path if path.is_absolute() else self.project_root / path

    def storage_path(self, layer: Literal["raw", "bronze", "silver", "offline_store"]) -> Path:
        path = getattr(self.project_config.storage, layer)
        return path if path.is_absolute() else self.project_root / path


def _read_yaml(path: Path) -> dict[str, object]:
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(content, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return content


def load_pipeline_config(
    project_root: Path,
    *,
    project_config_path: Path = Path("configs/project.yaml"),
    sources_config_path: Path = Path("configs/sources.yaml"),
) -> PipelineConfig:
    """Load and validate the configuration used by data pipelines."""
    root = project_root.resolve()
    project_path = (
        project_config_path if project_config_path.is_absolute() else root / project_config_path
    )
    sources_path = (
        sources_config_path if sources_config_path.is_absolute() else root / sources_config_path
    )
    return PipelineConfig(
        project_root=root,
        project_config=ProjectConfig.model_validate(_read_yaml(project_path)),
        sources_config=SourcesConfig.model_validate(_read_yaml(sources_path)),
    )
