"""Strict, versioned schema for Point-in-Time feature registry definitions."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

Aggregation = Literal["count", "sum", "avg", "max", "time_since_previous", "count_distinct"]

WINDOW_PATTERN = re.compile(r"^[1-9][0-9]*(?:s|m|h|d)$")
VALUE_AGGREGATIONS = {"sum", "avg", "max", "count_distinct"}
ZERO_DEFAULT_AGGREGATIONS = {"count", "sum", "count_distinct"}
NULL_DEFAULT_AGGREGATIONS = {"avg", "max", "time_since_previous"}


class FeatureDefinition(BaseModel):
    """One historical feature with aggregation-specific invariants."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    description: str = Field(min_length=1)
    aggregation: Aggregation
    window: str | None = None
    value_column: str | None = Field(default=None, min_length=1)
    ignore_null_values: bool = False
    no_history_value: int | float | None = None

    @model_validator(mode="after")
    def validate_aggregation_contract(self) -> FeatureDefinition:
        if self.aggregation == "time_since_previous":
            if self.window is not None:
                raise ValueError("time_since_previous must not define a bounded window")
        elif self.window is None:
            raise ValueError(f"aggregation '{self.aggregation}' requires window")

        if self.window is not None and not WINDOW_PATTERN.fullmatch(self.window):
            raise ValueError("window must be a positive integer followed by s, m, h, or d")

        if self.aggregation in VALUE_AGGREGATIONS:
            if self.value_column is None:
                raise ValueError(f"aggregation '{self.aggregation}' requires value_column")
            if not self.ignore_null_values:
                raise ValueError(
                    f"aggregation '{self.aggregation}' requires ignore_null_values=true"
                )
        else:
            if self.value_column is not None:
                raise ValueError(f"aggregation '{self.aggregation}' forbids value_column")
            if self.ignore_null_values:
                raise ValueError(
                    f"aggregation '{self.aggregation}' forbids ignore_null_values=true"
                )

        if self.aggregation in ZERO_DEFAULT_AGGREGATIONS:
            if self.no_history_value != 0:
                raise ValueError(f"aggregation '{self.aggregation}' requires no_history_value=0")
        elif self.aggregation in NULL_DEFAULT_AGGREGATIONS:
            if self.no_history_value is not None:
                raise ValueError(
                    f"aggregation '{self.aggregation}' requires no_history_value=null"
                )
        return self

    def semantic_signature(self) -> tuple[object, ...]:
        """Return fields that must match across primary and secondary entity views."""
        return (
            self.name,
            self.aggregation,
            self.window,
            self.value_column,
            self.ignore_null_values,
            self.no_history_value,
        )


class FeatureSetDefinition(BaseModel):
    """PIT, entity and naming contract shared by all features in one view."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    version: int = Field(ge=1)
    entity_key: Literal["card_address_entity_id", "card_entity_id"]
    source: Literal["silver_transactions"]
    event_timestamp: Literal["event_time"]
    observation_id: Literal["TransactionID"]
    ordering_columns: list[str] = Field(min_length=2, max_length=2)
    cutoff_policy: Literal["lexicographic_strict_before"]
    same_timestamp_policy: Literal["lower_transaction_id_is_earlier"]
    current_event_policy: Literal["exclude"]
    window_start_boundary: Literal["inclusive"]
    output_prefix: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*_$")
    owner: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_pit_contract(self) -> FeatureSetDefinition:
        if self.ordering_columns != [self.event_timestamp, self.observation_id]:
            raise ValueError("ordering_columns must equal [event_time, TransactionID]")

        expected_prefix = {
            "card_address_entity_id": "card_addr_",
            "card_entity_id": "card_",
        }[self.entity_key]
        if self.output_prefix != expected_prefix:
            raise ValueError(
                f"entity_key '{self.entity_key}' requires output_prefix '{expected_prefix}'"
            )
        return self


class FeatureRegistry(BaseModel):
    """Complete YAML document for one entity feature view."""

    model_config = ConfigDict(extra="forbid")

    feature_set: FeatureSetDefinition
    features: list[FeatureDefinition] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_outputs(self) -> FeatureRegistry:
        names = [feature.name for feature in self.features]
        if len(names) != len(set(names)):
            duplicates = sorted({name for name in names if names.count(name) > 1})
            raise ValueError(f"feature names must be unique; duplicates={duplicates}")

        outputs = [f"{self.feature_set.output_prefix}{name}" for name in names]
        if len(outputs) != len(set(outputs)):
            raise ValueError("rendered output column names must be unique")
        return self

    @property
    def output_columns(self) -> list[str]:
        return [f"{self.feature_set.output_prefix}{feature.name}" for feature in self.features]


def _read_yaml(path: Path) -> dict[str, object]:
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(content, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return content


def load_feature_registry(path: Path) -> FeatureRegistry:
    """Read and validate one feature registry file."""
    return FeatureRegistry.model_validate(_read_yaml(path))


def validate_registry_pair(primary: FeatureRegistry, secondary: FeatureRegistry) -> None:
    """Ensure both entity views expose the same logical feature semantics."""
    if primary.feature_set.entity_key != "card_address_entity_id":
        raise ValueError("primary registry must use card_address_entity_id")
    if secondary.feature_set.entity_key != "card_entity_id":
        raise ValueError("secondary registry must use card_entity_id")
    if primary.feature_set.version != secondary.feature_set.version:
        raise ValueError("primary and secondary feature-set versions must match")

    primary_signatures = [feature.semantic_signature() for feature in primary.features]
    secondary_signatures = [feature.semantic_signature() for feature in secondary.features]
    if primary_signatures != secondary_signatures:
        raise ValueError(
            "primary and secondary registries must define the same ordered logical features"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate versioned PIT feature registries")
    parser.add_argument(
        "--primary",
        type=Path,
        default=Path("configs/features/transaction_velocity_v1.yaml"),
    )
    parser.add_argument(
        "--secondary",
        type=Path,
        default=Path("configs/features/transaction_velocity_card_v1.yaml"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        primary = load_feature_registry(args.primary)
        secondary = load_feature_registry(args.secondary)
        validate_registry_pair(primary, secondary)
    except (OSError, ValueError) as exc:
        print(f"[feature-registry] invalid: {exc}", file=sys.stderr)
        return 1

    for path, registry in ((args.primary, primary), (args.secondary, secondary)):
        print(
            f"[valid] {path}: {registry.feature_set.name} "
            f"v{registry.feature_set.version}, {len(registry.features)} features"
        )
    print(f"[feature-registry] success: {len(primary.output_columns) * 2} output columns")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
