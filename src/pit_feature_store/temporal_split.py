"""Validate and audit fixed chronological model-evaluation splits."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_CONFIG = Path("configs/training_split.yaml")
DEFAULT_SOURCE_GLOB = Path("data/silver/transactions/dataset_split=train/**/*.parquet")
DEFAULT_REPORT = Path("reports/generated/temporal_split_report.json")
SPLIT_NAMES = ("train", "validation", "internal_test")


class SplitProportions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    train: float = Field(gt=0, lt=1)
    validation: float = Field(gt=0, lt=1)
    internal_test: float = Field(gt=0, lt=1)

    @model_validator(mode="after")
    def validate_total(self) -> SplitProportions:
        if abs(self.train + self.validation + self.internal_test - 1.0) > 1e-9:
            raise ValueError("target proportions must sum to 1.0")
        return self


class SplitBoundaries(BaseModel):
    model_config = ConfigDict(extra="forbid")

    validation_start_transaction_dt: int = Field(ge=0)
    internal_test_start_transaction_dt: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_order(self) -> SplitBoundaries:
        if self.validation_start_transaction_dt >= self.internal_test_start_transaction_dt:
            raise ValueError("validation boundary must be earlier than internal-test boundary")
        return self


class EventTimeReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    validation_start: str
    internal_test_start: str


class TemporalSplitConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    source_split: str = "train"
    time_column: str = "TransactionDT"
    observation_id: str = "TransactionID"
    label_column: str = "isFraud"
    strategy: str = "fixed_transaction_dt_boundaries"
    boundary_policy: str = "start_inclusive_end_exclusive"
    boundary_alignment_seconds: int = Field(ge=1)
    target_proportions: SplitProportions
    boundaries: SplitBoundaries
    synthetic_event_time_reference: EventTimeReference

    @model_validator(mode="after")
    def validate_contract(self) -> TemporalSplitConfig:
        expected = {
            "source_split": "train",
            "time_column": "TransactionDT",
            "observation_id": "TransactionID",
            "label_column": "isFraud",
            "strategy": "fixed_transaction_dt_boundaries",
            "boundary_policy": "start_inclusive_end_exclusive",
        }
        for field, value in expected.items():
            if getattr(self, field) != value:
                raise ValueError(f"{field} must equal {value!r}")
        boundaries = (
            self.boundaries.validation_start_transaction_dt,
            self.boundaries.internal_test_start_transaction_dt,
        )
        if any(value % self.boundary_alignment_seconds for value in boundaries):
            raise ValueError("split boundaries must align to boundary_alignment_seconds")
        return self

    def split_name(self, transaction_dt: int) -> str:
        if transaction_dt < self.boundaries.validation_start_transaction_dt:
            return "train"
        if transaction_dt < self.boundaries.internal_test_start_transaction_dt:
            return "validation"
        return "internal_test"

    def sql_case(self) -> str:
        validation = self.boundaries.validation_start_transaction_dt
        internal_test = self.boundaries.internal_test_start_transaction_dt
        return (
            f"CASE WHEN TransactionDT < {validation} THEN 'train' "
            f"WHEN TransactionDT < {internal_test} THEN 'validation' "
            "ELSE 'internal_test' END"
        )


def load_temporal_split_config(path: Path) -> TemporalSplitConfig:
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(content, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return TemporalSplitConfig.model_validate(content)


def audit_temporal_split(
    source_glob: Path,
    config: TemporalSplitConfig,
    report_path: Path,
) -> dict[str, object]:
    connection = duckdb.connect()
    source = str(source_glob).replace("'", "''")
    split_case = config.sql_case()
    try:
        quality = connection.execute(
            f"""
            SELECT COUNT(*)::BIGINT,
                   COUNT(*) FILTER (WHERE TransactionID IS NULL)::BIGINT,
                   COUNT(*) FILTER (WHERE TransactionDT IS NULL)::BIGINT,
                   COUNT(*) FILTER (WHERE isFraud NOT IN (0, 1) OR isFraud IS NULL)::BIGINT,
                   COUNT(*) - COUNT(DISTINCT TransactionID)::BIGINT
            FROM read_parquet('{source}', hive_partitioning=true)
            """
        ).fetchone()
        total_rows, null_ids, null_times, invalid_labels, duplicate_ids = map(int, quality)
        if any((null_ids, null_times, invalid_labels, duplicate_ids)):
            raise ValueError(
                "invalid temporal-split source: "
                f"null_ids={null_ids}, null_times={null_times}, "
                f"invalid_labels={invalid_labels}, duplicate_ids={duplicate_ids}"
            )

        rows = connection.execute(
            f"""
            SELECT {split_case} AS model_split,
                   COUNT(*)::BIGINT AS row_count,
                   MIN(TransactionDT)::BIGINT AS min_transaction_dt,
                   MAX(TransactionDT)::BIGINT AS max_transaction_dt,
                   SUM(isFraud)::BIGINT AS fraud_count,
                   AVG(isFraud)::DOUBLE AS fraud_rate
            FROM read_parquet('{source}', hive_partitioning=true)
            GROUP BY model_split
            """
        ).fetchall()
    finally:
        connection.close()

    metrics = {
        name: {
            "row_count": int(row_count),
            "row_proportion": row_count / total_rows,
            "min_transaction_dt": int(min_dt),
            "max_transaction_dt": int(max_dt),
            "fraud_count": int(fraud_count),
            "fraud_rate": float(fraud_rate),
        }
        for name, row_count, min_dt, max_dt, fraud_count, fraud_rate in rows
    }
    if set(metrics) != set(SPLIT_NAMES):
        raise ValueError(f"expected all three temporal splits, found {sorted(metrics)}")
    if sum(item["row_count"] for item in metrics.values()) != total_rows:
        raise ValueError("temporal split row reconciliation failed")
    if not (
        metrics["train"]["max_transaction_dt"]
        < metrics["validation"]["min_transaction_dt"]
        <= metrics["validation"]["max_transaction_dt"]
        < metrics["internal_test"]["min_transaction_dt"]
    ):
        raise ValueError("temporal split overlap or ordering violation")

    report: dict[str, object] = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "config_name": config.name,
        "config_version": config.version,
        "source_glob": str(source_glob),
        "strategy": config.strategy,
        "boundary_policy": config.boundary_policy,
        "boundary_alignment_seconds": config.boundary_alignment_seconds,
        "boundaries": config.boundaries.model_dump(),
        "total_rows": total_rows,
        "quality": {
            "null_transaction_ids": null_ids,
            "null_transaction_dt": null_times,
            "invalid_labels": invalid_labels,
            "duplicate_transaction_ids": duplicate_ids,
            "temporal_overlap": False,
        },
        "splits": {name: metrics[name] for name in SPLIT_NAMES},
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit fixed chronological model splits")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--source-glob", type=Path, default=DEFAULT_SOURCE_GLOB)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_temporal_split_config(args.config)
    print(f"[temporal-split] config={config.name} v{config.version}")
    report = audit_temporal_split(args.source_glob, config, args.report)
    for name in SPLIT_NAMES:
        metrics = report["splits"][name]
        print(
            f"[{name}] rows={metrics['row_count']}, "
            f"proportion={metrics['row_proportion']:.4f}, "
            f"fraud_rate={metrics['fraud_rate']:.6f}, "
            f"TransactionDT={metrics['min_transaction_dt']}..{metrics['max_transaction_dt']}"
        )
    print(f"[temporal-split] success: report={args.report}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
