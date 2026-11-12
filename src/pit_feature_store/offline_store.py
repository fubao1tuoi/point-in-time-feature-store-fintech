"""Materialize versioned Point-in-Time features into an offline Parquet table."""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from pit_feature_store.feature_registry import (
    FeatureRegistry,
    load_feature_registry,
    validate_registry_pair,
)
from pit_feature_store.pit_features import materialize_feature_view, materialize_observations

DEFAULT_SOURCE_GLOB = Path("data/silver/transactions/**/*.parquet")
DEFAULT_OUTPUT_ROOT = Path("data/offline_store/transaction_features")
DEFAULT_PRIMARY_REGISTRY = Path("configs/features/transaction_velocity_v1.yaml")
DEFAULT_SECONDARY_REGISTRY = Path(
    "configs/features/transaction_velocity_card_v1.yaml"
)


class OfflineMaterializationError(ValueError):
    """Raised when a versioned offline feature table cannot be published safely."""


@dataclass(frozen=True)
class OfflineFeatureMetrics:
    run_id: str
    feature_table_version: int
    output_path: Path
    row_count: int
    unique_transaction_ids: int
    feature_column_count: int
    partition_count: int
    parquet_file_count: int
    min_observation_date: str
    max_observation_date: str
    parquet_size_bytes: int
    semantic_fingerprint: str
    manifest_path: Path


def _sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _create_source_view(
    connection: duckdb.DuckDBPyConnection, source_glob: Path
) -> None:
    connection.execute(
        "CREATE OR REPLACE TEMP VIEW silver_transactions AS "
        f"SELECT * FROM read_parquet({_sql_literal(source_glob)}, hive_partitioning=true)"
    )


def _create_offline_table(
    connection: duckdb.DuckDBPyConnection,
    primary: FeatureRegistry,
    secondary: FeatureRegistry,
    feature_table_version: int,
    start_time: str | None,
    end_time: str | None,
    *,
    optimize_history: bool = True,
) -> dict[str, int | bool]:
    cutoff = ""
    if start_time is not None and end_time is not None:
        cutoff = (
            f"WHERE event_time >= TIMESTAMPTZ {_sql_literal(start_time)} "
            f"AND event_time < TIMESTAMPTZ {_sql_literal(end_time)}"
        )
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE selected_observation_source AS "
        f"SELECT * FROM silver_transactions {cutoff}"
    )
    materialize_observations(connection, "selected_observation_source")
    optimization_applied = optimize_history and start_time is not None
    primary_history = "silver_transactions"
    secondary_history = "silver_transactions"
    if optimization_applied:
        history_limit = (
            "history.event_time <= "
            "(SELECT MAX(prediction_time) FROM pit_observations)"
        )
        for table_name, entity_key in (
            ("primary_history_source", primary.feature_set.entity_key),
            ("secondary_history_source", secondary.feature_set.entity_key),
        ):
            entity = '"' + entity_key.replace('"', '""') + '"'
            connection.execute(
                f"""
                CREATE OR REPLACE TEMP TABLE {table_name} AS
                SELECT history.*
                FROM silver_transactions AS history
                SEMI JOIN (
                    SELECT DISTINCT {entity}
                    FROM pit_observations
                    WHERE {entity} IS NOT NULL
                ) AS selected_entities
                  ON history.{entity} = selected_entities.{entity}
                WHERE {history_limit}
                """
            )
        primary_history = "primary_history_source"
        secondary_history = "secondary_history_source"
    materialize_feature_view(
        connection,
        "pit_observations",
        primary_history,
        primary,
        output_table="primary_features",
    )
    materialize_feature_view(
        connection,
        "pit_observations",
        secondary_history,
        secondary,
        output_table="secondary_features",
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE offline_transaction_features AS
        SELECT
            observation.TransactionID,
            observation.event_time,
            observation.prediction_time,
            CAST(timezone('UTC', observation.prediction_time) AS DATE) AS observation_date,
            primary_features.* EXCLUDE (TransactionID),
            secondary_features.* EXCLUDE (TransactionID),
            {feature_table_version}::INTEGER AS feature_table_version,
            {_sql_literal(primary.feature_set.name)}::VARCHAR
                AS primary_feature_set_name,
            {primary.feature_set.version}::INTEGER AS primary_feature_set_version,
            {_sql_literal(secondary.feature_set.name)}::VARCHAR
                AS secondary_feature_set_name,
            {secondary.feature_set.version}::INTEGER AS secondary_feature_set_version
        FROM pit_observations AS observation
        JOIN primary_features USING (TransactionID)
        JOIN secondary_features USING (TransactionID)
        ORDER BY observation.TransactionID
        """
    )
    full_rows = int(connection.execute("SELECT COUNT(*) FROM silver_transactions").fetchone()[0])
    primary_rows = int(connection.execute(f"SELECT COUNT(*) FROM {primary_history}").fetchone()[0])
    secondary_rows = int(
        connection.execute(f"SELECT COUNT(*) FROM {secondary_history}").fetchone()[0]
    )
    return {
        "optimization_applied": optimization_applied,
        "full_history_rows": full_rows,
        "primary_history_candidate_rows": primary_rows,
        "secondary_history_candidate_rows": secondary_rows,
    }


def _validate_cutoff(start_time: str | None, end_time: str | None) -> None:
    if (start_time is None) != (end_time is None):
        raise OfflineMaterializationError("start_time and end_time must be provided together")
    if start_time is None:
        return
    try:
        start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OfflineMaterializationError("start_time and end_time must be ISO-8601") from exc
    if start.tzinfo is None or end.tzinfo is None:
        raise OfflineMaterializationError("start_time and end_time must include timezone")
    if start >= end:
        raise OfflineMaterializationError("start_time must be earlier than end_time")
    if (
        start.utcoffset().total_seconds() != 0
        or end.utcoffset().total_seconds() != 0
        or start.time() != datetime.min.time()
        or end.time() != datetime.min.time()
    ):
        raise OfflineMaterializationError(
            "backfill boundaries must be UTC midnight because output partitions are daily"
        )


def _source_checksum(source_glob: Path) -> tuple[str, int]:
    paths = sorted(Path(path) for path in glob.glob(str(source_glob), recursive=True))
    files = [path for path in paths if path.is_file()]
    if not files:
        raise OfflineMaterializationError(f"no source files matched: {source_glob}")
    digest = hashlib.sha256()
    for path in files:
        file_digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                file_digest.update(chunk)
        digest.update(path.name.encode())
        digest.update(file_digest.digest())
    return digest.hexdigest(), len(files)


def _semantic_fingerprint(
    connection: duckdb.DuckDBPyConnection, table: str
) -> str:
    columns = [
        row[0]
        for row in connection.execute(f"DESCRIBE SELECT * FROM {table}").fetchall()
    ]
    fields = ", ".join(
        f'"{column}" := "{column}"' for column in sorted(columns)
    )
    xor_hash, rows = connection.execute(
        f"""
        SELECT BIT_XOR(HASH(TO_JSON(STRUCT_PACK({fields}))))::VARCHAR,
               COUNT(*)::BIGINT
        FROM {table}
        """
    ).fetchone()
    return f"rows={rows};xor64={xor_hash}"


def _publish_backfill_partitions(staging: Path, final: Path, run_id: str) -> None:
    staged_partitions = sorted(staging.glob("observation_date=*"))
    if not staged_partitions:
        raise OfflineMaterializationError("backfill produced no observation-date partitions")
    backup = final.parent / f".backup_{run_id}"
    backup.mkdir(parents=True, exist_ok=False)
    published: list[tuple[Path, Path | None]] = []
    try:
        for staged_partition in staged_partitions:
            target = final / staged_partition.name
            saved = None
            if target.exists():
                saved = backup / staged_partition.name
                target.rename(saved)
            published.append((target, saved))
            staged_partition.rename(target)
    except Exception:
        for target, saved in reversed(published):
            if target.exists():
                shutil.rmtree(target)
            if saved is not None and saved.exists():
                saved.rename(target)
        raise
    finally:
        if backup.exists():
            shutil.rmtree(backup)


def materialize_offline_feature_table(
    source_glob: Path,
    output_root: Path,
    primary_registry_path: Path,
    secondary_registry_path: Path,
    *,
    feature_table_version: int,
    start_time: str | None = None,
    end_time: str | None = None,
    backfill: bool = False,
    optimize_history: bool = True,
    connection: duckdb.DuckDBPyConnection | None = None,
) -> OfflineFeatureMetrics:
    """Build and atomically publish one immutable versioned Parquet feature table."""
    if feature_table_version < 1:
        raise OfflineMaterializationError("feature_table_version must be >= 1")
    _validate_cutoff(start_time, end_time)
    if backfill and start_time is None:
        raise OfflineMaterializationError("backfill requires start_time and end_time")

    primary = load_feature_registry(primary_registry_path)
    secondary = load_feature_registry(secondary_registry_path)
    validate_registry_pair(primary, secondary)

    final_directory = output_root / f"v{feature_table_version}"
    if final_directory.exists() and not backfill:
        raise OfflineMaterializationError(
            f"immutable feature-table version already exists: {final_directory}"
        )
    if backfill and not final_directory.exists():
        raise OfflineMaterializationError(
            f"cannot backfill missing feature-table version: {final_directory}"
        )

    run_id = f"offline_{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
    started_at = datetime.now(UTC)
    source_checksum, source_file_count = _source_checksum(source_glob)
    owns_connection = connection is None
    db = connection or duckdb.connect()
    staging_directory = output_root / f".staging_{uuid.uuid4().hex}"
    staged_glob = staging_directory / "**" / "*.parquet"
    try:
        print("[1/4] validating feature registries and loading Silver source")
        _create_source_view(db, source_glob)
        print("[2/4] computing primary and secondary PIT feature views")
        optimization_stats = _create_offline_table(
            db,
            primary,
            secondary,
            feature_table_version,
            start_time,
            end_time,
            optimize_history=optimize_history,
        )

        row_count, unique_ids, source_partition_count, min_date, max_date = db.execute(
            """
            SELECT COUNT(*)::BIGINT,
                   COUNT(DISTINCT TransactionID)::BIGINT,
                   COUNT(DISTINCT observation_date)::BIGINT,
                   MIN(observation_date)::VARCHAR,
                   MAX(observation_date)::VARCHAR
            FROM offline_transaction_features
            """
        ).fetchone()
        if row_count != unique_ids:
            raise OfflineMaterializationError(
                f"offline table grain violation: rows={row_count}, unique_ids={unique_ids}"
            )
        if row_count == 0:
            raise OfflineMaterializationError("selected observation range contains no rows")

        semantic_fingerprint = _semantic_fingerprint(db, "offline_transaction_features")

        print("[3/4] writing and validating staged Parquet")
        output_root.mkdir(parents=True, exist_ok=True)
        db.execute(
            "COPY offline_transaction_features TO "
            f"{_sql_literal(staging_directory)} "
            "(FORMAT PARQUET, COMPRESSION ZSTD, "
            "PARTITION_BY (observation_date), FILENAME_PATTERN 'part_{i}')"
        )
        parquet_rows, version_mismatches, partition_count, parquet_min_date, parquet_max_date = (
            db.execute(
            f"""
            SELECT COUNT(*)::BIGINT,
                   COUNT(*) FILTER (
                       WHERE feature_table_version != {feature_table_version}
                   )::BIGINT,
                   COUNT(DISTINCT observation_date)::BIGINT,
                   MIN(observation_date)::VARCHAR,
                   MAX(observation_date)::VARCHAR
            FROM read_parquet({_sql_literal(staged_glob)}, hive_partitioning=true)
            """
            ).fetchone()
        )
        if (
            parquet_rows != row_count
            or version_mismatches
            or partition_count != source_partition_count
            or parquet_min_date != min_date
            or parquet_max_date != max_date
        ):
            raise OfflineMaterializationError(
                "staged Parquet reconciliation failed: "
                f"source_rows={row_count}, parquet_rows={parquet_rows}, "
                f"version_mismatches={version_mismatches}, "
                f"source_partitions={source_partition_count}, "
                f"parquet_partitions={partition_count}, "
                f"source_range={min_date}..{max_date}, "
                f"parquet_range={parquet_min_date}..{parquet_max_date}"
            )

        output_columns = [
            row[0]
            for row in db.execute(
                "DESCRIBE SELECT * FROM read_parquet("
                f"{_sql_literal(staged_glob)}, hive_partitioning=true)"
            ).fetchall()
        ]
        missing_features = sorted(
            set(primary.output_columns + secondary.output_columns) - set(output_columns)
        )
        if missing_features:
            raise OfflineMaterializationError(
                f"staged Parquet missing feature columns: {missing_features}"
            )

        print("[4/4] publishing immutable version directory")
        completed_at = datetime.now(UTC)
        manifest = {
            "run_id": run_id,
            "status": "success",
            "mode": "backfill" if backfill else "initial",
            "started_at_utc": started_at.isoformat(),
            "completed_at_utc": completed_at.isoformat(),
            "duration_seconds": round((completed_at - started_at).total_seconds(), 3),
            "source": {
                "path_glob": str(source_glob),
                "checksum_algorithm": "sha256_of_ordered_file_sha256",
                "checksum_sha256": source_checksum,
                "file_count": source_file_count,
            },
            "feature_table_version": feature_table_version,
            "primary_feature_set": {
                "name": primary.feature_set.name,
                "version": primary.feature_set.version,
            },
            "secondary_feature_set": {
                "name": secondary.feature_set.name,
                "version": secondary.feature_set.version,
            },
            "cutoff": {
                "start_time_inclusive": start_time,
                "end_time_exclusive": end_time,
                "min_observation_date": str(min_date),
                "max_observation_date": str(max_date),
            },
            "quality": {
                "row_count": int(row_count),
                "unique_transaction_ids": int(unique_ids),
                "partition_count": int(partition_count),
                "feature_column_count": len(
                    primary.output_columns + secondary.output_columns
                ),
                "semantic_fingerprint": semantic_fingerprint,
            },
            "optimization": optimization_stats,
        }
        if backfill:
            _publish_backfill_partitions(staging_directory, final_directory, run_id)
        else:
            staging_directory.rename(final_directory)
        manifest_directory = final_directory / "manifests"
        manifest_directory.mkdir(exist_ok=True)
        manifest_path = manifest_directory / f"{run_id}.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        parquet_files = list(final_directory.rglob("*.parquet"))
        parquet_size = sum(path.stat().st_size for path in parquet_files)
        print(f"[offline-store] success: {final_directory}")
        return OfflineFeatureMetrics(
            run_id=run_id,
            feature_table_version=feature_table_version,
            output_path=final_directory,
            row_count=int(row_count),
            unique_transaction_ids=int(unique_ids),
            feature_column_count=len(primary.output_columns + secondary.output_columns),
            partition_count=int(partition_count),
            parquet_file_count=len(parquet_files),
            min_observation_date=str(min_date),
            max_observation_date=str(max_date),
            parquet_size_bytes=parquet_size,
            semantic_fingerprint=semantic_fingerprint,
            manifest_path=manifest_path,
        )
    finally:
        if staging_directory.exists():
            shutil.rmtree(staging_directory)
        if owns_connection:
            db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Materialize versioned offline PIT features")
    parser.add_argument("--source-glob", type=Path, default=DEFAULT_SOURCE_GLOB)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--primary", type=Path, default=DEFAULT_PRIMARY_REGISTRY)
    parser.add_argument("--secondary", type=Path, default=DEFAULT_SECONDARY_REGISTRY)
    parser.add_argument("--feature-table-version", type=int, default=1)
    parser.add_argument("--start-time")
    parser.add_argument("--end-time")
    parser.add_argument("--backfill", action="store_true")
    parser.add_argument("--disable-history-optimization", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    materialize_offline_feature_table(
        args.source_glob,
        args.output_root,
        args.primary,
        args.secondary,
        feature_table_version=args.feature_table_version,
        start_time=args.start_time,
        end_time=args.end_time,
        backfill=args.backfill,
        optimize_history=not args.disable_history_optimization,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
