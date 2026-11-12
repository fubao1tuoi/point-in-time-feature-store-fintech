"""Leakage audit, edge hardening, optimization benchmark and failure logging."""

from __future__ import annotations

import argparse
import glob
import json
import shutil
import time
import traceback
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from pit_feature_store.feature_registry import load_feature_registry, validate_registry_pair
from pit_feature_store.offline_store import _create_offline_table, _semantic_fingerprint
from pit_feature_store.temporal_split import load_temporal_split_config

DEFAULT_CONFIG = Path("configs/hardening.yaml")


class HardeningError(ValueError):
    """Raised when a hardening invariant fails."""


class BenchmarkConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_rows: int = Field(ge=100)
    entity_count: int = Field(ge=2)
    seconds_between_events: int = Field(ge=1)
    start_time: str
    end_time: str

    @model_validator(mode="after")
    def validate_cardinality(self) -> BenchmarkConfig:
        if self.entity_count >= self.source_rows:
            raise ValueError("benchmark entity_count must be smaller than source_rows")
        return self


class HardeningConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    temporal_split_config: Path
    preprocessing_artifact: Path
    training_dataset_manifest_glob: str
    primary_feature_registry: Path
    secondary_feature_registry: Path
    output_root: Path
    benchmark: BenchmarkConfig


def load_hardening_config(path: Path) -> HardeningConfig:
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(content, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return HardeningConfig.model_validate(content)


class AuditLogger:
    """Append-only JSONL stage logger that flushes every event."""

    def __init__(self, path: Path, run_id: str) -> None:
        self.path = path
        self.run_id = run_id
        path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, stage: str, status: str, **details: object) -> None:
        record = {
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "run_id": self.run_id,
            "stage": stage,
            "status": status,
            **details,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()


def _run_stage(logger: AuditLogger, name: str, operation: Callable[[], Any]) -> Any:
    started = time.perf_counter()
    logger.write(name, "started")
    try:
        result = operation()
    except Exception as exc:
        logger.write(
            name,
            "failed",
            duration_seconds=round(time.perf_counter() - started, 6),
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        raise
    logger.write(name, "success", duration_seconds=round(time.perf_counter() - started, 6))
    return result


def _single_json(pattern: str) -> dict[str, object]:
    paths = [Path(value) for value in glob.glob(pattern)]
    if len(paths) != 1:
        raise HardeningError(f"expected one manifest for {pattern}, found {len(paths)}")
    return json.loads(paths[0].read_text(encoding="utf-8"))


def audit_leakage_contracts(config: HardeningConfig) -> dict[str, object]:
    split = load_temporal_split_config(config.temporal_split_config)
    preprocessing = json.loads(config.preprocessing_artifact.read_text(encoding="utf-8"))
    training = _single_json(config.training_dataset_manifest_glob)
    primary = load_feature_registry(config.primary_feature_registry)
    secondary = load_feature_registry(config.secondary_feature_registry)
    validate_registry_pair(primary, secondary)

    registry_checks: dict[str, bool] = {}
    for label, registry in (("primary", primary), ("secondary", secondary)):
        feature_set = registry.feature_set
        registry_checks[f"{label}_strict_lexicographic_cutoff"] = (
            feature_set.cutoff_policy == "lexicographic_strict_before"
        )
        registry_checks[f"{label}_current_event_excluded"] = (
            feature_set.current_event_policy == "exclude"
        )
        registry_checks[f"{label}_event_then_id_order"] = feature_set.ordering_columns == [
            "event_time",
            "TransactionID",
        ]
        registry_checks[f"{label}_label_not_used"] = all(
            feature.value_column != "isFraud" for feature in registry.features
        )

    validation_start = split.boundaries.validation_start_transaction_dt
    test_start = split.boundaries.internal_test_start_transaction_dt
    fit_policy = preprocessing["fit_policy"]
    preprocessing_checks = {
        "fit_split_is_train": fit_policy["model_split"] == "train",
        "fit_end_equals_validation_start": (
            fit_policy["transaction_dt_end_exclusive"] == validation_start
        ),
        "observed_fit_max_before_validation": (
            fit_policy["observed_max_transaction_dt"] < validation_start
        ),
    }
    splits = training["splits"]
    temporal_checks = {
        "train_before_validation": splits["train"]["max_transaction_dt"] < validation_start,
        "validation_starts_at_boundary": (
            splits["validation"]["min_transaction_dt"] >= validation_start
        ),
        "validation_before_test": splits["validation"]["max_transaction_dt"] < test_start,
        "test_starts_at_boundary": splits["internal_test"]["min_transaction_dt"] >= test_start,
        "all_rows_unique": (
            training["quality"]["output_rows"]
            == training["quality"]["unique_transaction_ids"]
        ),
        "no_missing_pit_join": training["quality"]["missing_offline_feature_rows"] == 0,
    }
    checks = {**registry_checks, **preprocessing_checks, **temporal_checks}
    failed = sorted(name for name, passed in checks.items() if not passed)
    if failed:
        raise HardeningError(f"leakage contract checks failed: {failed}")
    return {
        "status": "passed",
        "check_count": len(checks),
        "checks": checks,
        "validation_start_transaction_dt": validation_start,
        "internal_test_start_transaction_dt": test_start,
    }


def _create_benchmark_source(db: duckdb.DuckDBPyConnection, config: BenchmarkConfig) -> None:
    db.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE silver_transactions AS
        SELECT
            1000000 + i AS TransactionID,
            TIMESTAMPTZ '2017-01-01 00:00:00+00'
              + i * INTERVAL '{config.seconds_between_events} seconds' AS event_time,
            10.0 + (i % 500) AS TransactionAmt,
            'P' || CAST(i % 5 AS VARCHAR) AS ProductCD,
            'card_' || CAST(i % {config.entity_count} AS VARCHAR) AS card_entity_id,
            'card_addr_' || CAST(i % {config.entity_count} AS VARCHAR)
              AS card_address_entity_id
        FROM range({config.source_rows}) AS source(i)
        """
    )


def benchmark_optimization(config: HardeningConfig) -> dict[str, object]:
    primary = load_feature_registry(config.primary_feature_registry)
    secondary = load_feature_registry(config.secondary_feature_registry)
    benchmark = config.benchmark
    db = duckdb.connect()
    try:
        _create_benchmark_source(db, benchmark)
        start = time.perf_counter()
        baseline_stats = _create_offline_table(
            db,
            primary,
            secondary,
            1,
            benchmark.start_time,
            benchmark.end_time,
            optimize_history=False,
        )
        baseline_seconds = time.perf_counter() - start
        db.execute(
            "CREATE OR REPLACE TEMP TABLE baseline_output AS "
            "SELECT * FROM offline_transaction_features"
        )
        baseline_fingerprint = _semantic_fingerprint(db, "baseline_output")

        start = time.perf_counter()
        optimized_stats = _create_offline_table(
            db,
            primary,
            secondary,
            1,
            benchmark.start_time,
            benchmark.end_time,
            optimize_history=True,
        )
        optimized_seconds = time.perf_counter() - start
        optimized_fingerprint = _semantic_fingerprint(db, "offline_transaction_features")
        differences = int(
            db.execute(
                """
                SELECT COUNT(*) FROM (
                    (SELECT * FROM baseline_output EXCEPT ALL
                     SELECT * FROM offline_transaction_features)
                    UNION ALL
                    (SELECT * FROM offline_transaction_features EXCEPT ALL
                     SELECT * FROM baseline_output)
                )
                """
            ).fetchone()[0]
        )
        if differences or baseline_fingerprint != optimized_fingerprint:
            raise HardeningError(
                "optimized output differs from baseline: "
                f"differences={differences}, baseline={baseline_fingerprint}, "
                f"optimized={optimized_fingerprint}"
            )
        baseline_candidates = (
            baseline_stats["primary_history_candidate_rows"]
            + baseline_stats["secondary_history_candidate_rows"]
        )
        optimized_candidates = (
            optimized_stats["primary_history_candidate_rows"]
            + optimized_stats["secondary_history_candidate_rows"]
        )
        return {
            "status": "passed",
            "source_rows": benchmark.source_rows,
            "observation_rows": int(
                db.execute("SELECT COUNT(*) FROM offline_transaction_features").fetchone()[0]
            ),
            "baseline": {
                "runtime_seconds": round(baseline_seconds, 6),
                "logical_history_candidate_rows": baseline_candidates,
                **baseline_stats,
            },
            "optimized": {
                "runtime_seconds": round(optimized_seconds, 6),
                "logical_history_candidate_rows": optimized_candidates,
                **optimized_stats,
            },
            "improvement": {
                "runtime_speedup": baseline_seconds / optimized_seconds,
                "candidate_row_reduction_fraction": 1
                - (optimized_candidates / baseline_candidates),
            },
            "equivalence": {
                "different_rows": differences,
                "baseline_semantic_fingerprint": baseline_fingerprint,
                "optimized_semantic_fingerprint": optimized_fingerprint,
            },
            "optimization_scope": (
                "bounded backfill: observation cutoff enables partition pruning; "
                "history is semi-joined to selected primary/secondary entities and capped "
                "at maximum prediction time"
            ),
        }
    finally:
        db.close()


def run_hardening(config_path: Path = DEFAULT_CONFIG) -> dict[str, object]:
    config = load_hardening_config(config_path)
    output = config.output_root / f"v{config.version}"
    if output.exists():
        raise HardeningError(f"immutable hardening version already exists: {output}")
    run_id = f"hardening_{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
    staging = config.output_root / f".{run_id}.staging"
    audit_path = staging / "audit_log.jsonl"
    logger = AuditLogger(audit_path, run_id)
    started_at = datetime.now(UTC)
    print(f"[hardening] run_id={run_id}", flush=True)
    try:
        print("[1/3] auditing future aggregation, preprocessing and split overlap", flush=True)
        leakage = _run_stage(logger, "leakage_audit", lambda: audit_leakage_contracts(config))
        print("[2/3] benchmarking baseline versus optimized bounded backfill", flush=True)
        benchmark = _run_stage(
            logger, "optimization_benchmark", lambda: benchmark_optimization(config)
        )
        print("[3/3] writing hardening evidence", flush=True)
        completed_at = datetime.now(UTC)
        report: dict[str, object] = {
            "run_id": run_id,
            "status": "success",
            "name": config.name,
            "version": config.version,
            "started_at_utc": started_at.isoformat(),
            "completed_at_utc": completed_at.isoformat(),
            "duration_seconds": round((completed_at - started_at).total_seconds(), 3),
            "leakage_audit": leakage,
            "optimization_benchmark": benchmark,
            "edge_case_evidence": {
                "test_file": "tests/point_in_time/test_hardening_edge_cases.py",
                "covered": [
                    "null_entity",
                    "skewed_entity",
                    "same_timestamp_tie",
                    "late_arriving_event",
                    "future_event_invariance",
                ],
            },
            "failure_handling": {
                "audit_log": "audit_log.jsonl",
                "failed_run_logs": str(config.output_root / "failures"),
                "staging_is_not_published_on_failure": True,
            },
        }
        (staging / "hardening_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        logger.write("publish", "success")
        config.output_root.mkdir(parents=True, exist_ok=True)
        staging.rename(output)
        print(f"[hardening] success: {output}", flush=True)
        return report
    except Exception as exc:
        logger.write(
            "run",
            "failed",
            error_type=type(exc).__name__,
            error_message=str(exc),
            traceback=traceback.format_exc(),
        )
        failures = config.output_root / "failures"
        failures.mkdir(parents=True, exist_ok=True)
        if audit_path.exists():
            shutil.copy2(audit_path, failures / f"{run_id}.jsonl")
        if staging.exists():
            shutil.rmtree(staging)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Mốc 8 leakage and hardening audit")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    run_hardening(args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
