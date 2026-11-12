"""Migrate the legacy single-file offline store to UTC daily partitions."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import duckdb


class OfflineMigrationError(ValueError):
    """Raised when legacy offline-store migration cannot be completed safely."""


def _sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def migrate_legacy_offline_store(
    version_directory: Path,
    *,
    feature_table_version: int,
    connection: duckdb.DuckDBPyConnection | None = None,
) -> dict[str, object]:
    """Atomically replace a mixed legacy version with one clean partitioned dataset."""
    version_directory = version_directory.resolve()
    output_root = version_directory.parent
    legacy_file = version_directory / "features.parquet"
    if not legacy_file.is_file():
        raise OfflineMigrationError(f"legacy feature file not found: {legacy_file}")
    if version_directory.name != f"v{feature_table_version}":
        raise OfflineMigrationError("version directory and feature_table_version disagree")

    run_id = f"migration_{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
    staging = output_root / f".staging_{run_id}"
    backup = output_root / f".backup_{run_id}"
    if staging.exists() or backup.exists():
        raise OfflineMigrationError("migration staging or backup path already exists")

    owns_connection = connection is None
    db = connection or duckdb.connect()
    started_at = datetime.now(UTC)
    source_checksum = _sha256(legacy_file)
    try:
        print("[1/4] validating legacy full feature file")
        columns = [
            row[0]
            for row in db.execute(
                f"DESCRIBE SELECT * FROM read_parquet({_sql_literal(legacy_file)})"
            ).fetchall()
        ]
        required = {
            "TransactionID",
            "prediction_time",
            "feature_table_version",
        }
        missing = sorted(required - set(columns))
        if missing:
            raise OfflineMigrationError(f"legacy feature file missing columns: {missing}")

        source_rows, unique_ids, min_version, max_version = db.execute(
            f"""
            SELECT COUNT(*)::BIGINT, COUNT(DISTINCT TransactionID)::BIGINT,
                   MIN(feature_table_version)::INTEGER,
                   MAX(feature_table_version)::INTEGER
            FROM read_parquet({_sql_literal(legacy_file)})
            """
        ).fetchone()
        if source_rows != unique_ids:
            raise OfflineMigrationError(
                f"legacy source contains duplicate IDs: rows={source_rows}, unique={unique_ids}"
            )
        if min_version != feature_table_version or max_version != feature_table_version:
            raise OfflineMigrationError(
                f"legacy version mismatch: min={min_version}, max={max_version}"
            )

        print("[2/4] writing UTC observation-date partitions to staging")
        select_columns = ", ".join(
            _quote_identifier(column) for column in columns if column != "observation_date"
        )
        db.execute(
            f"""
            COPY (
                SELECT {select_columns},
                       CAST(timezone('UTC', prediction_time) AS DATE) AS observation_date
                FROM read_parquet({_sql_literal(legacy_file)})
            ) TO {_sql_literal(staging)}
            (FORMAT PARQUET, COMPRESSION ZSTD,
             PARTITION_BY (observation_date), FILENAME_PATTERN 'part_{{i}}')
            """
        )

        print("[3/4] reconciling staged dataset")
        staged_glob = staging / "observation_date=*" / "*.parquet"
        staged_rows, staged_unique, staged_min_version, staged_max_version = db.execute(
            f"""
            SELECT COUNT(*)::BIGINT, COUNT(DISTINCT TransactionID)::BIGINT,
                   MIN(feature_table_version)::INTEGER,
                   MAX(feature_table_version)::INTEGER
            FROM read_parquet({_sql_literal(staged_glob)}, hive_partitioning=true)
            """
        ).fetchone()
        if (staged_rows, staged_unique) != (source_rows, unique_ids):
            raise OfflineMigrationError(
                "migration row reconciliation failed: "
                f"source={source_rows}/{unique_ids}, staged={staged_rows}/{staged_unique}"
            )
        if (
            staged_min_version != feature_table_version
            or staged_max_version != feature_table_version
        ):
            raise OfflineMigrationError("staged feature version mismatch")

        partition_count = len(list(staging.glob("observation_date=*")))
        parquet_files = list(staging.rglob("*.parquet"))
        completed_at = datetime.now(UTC)
        manifest: dict[str, object] = {
            "run_id": run_id,
            "status": "success",
            "mode": "legacy_single_file_to_utc_daily_partitions",
            "started_at_utc": started_at.isoformat(),
            "completed_at_utc": completed_at.isoformat(),
            "source": {
                "path": str(legacy_file),
                "checksum_algorithm": "sha256",
                "checksum_sha256": source_checksum,
            },
            "feature_table_version": feature_table_version,
            "partition_timezone": "UTC",
            "partition_column": "observation_date",
            "quality": {
                "row_count": int(staged_rows),
                "unique_transaction_ids": int(staged_unique),
                "duplicate_transaction_ids": int(staged_rows - staged_unique),
                "partition_count": partition_count,
                "parquet_file_count": len(parquet_files),
            },
        }
        manifest_directory = staging / "manifests"
        manifest_directory.mkdir()
        manifest_path = manifest_directory / f"{run_id}.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

        print("[4/4] atomically replacing mixed legacy layout")
        version_directory.rename(backup)
        try:
            staging.rename(version_directory)
        except Exception:
            backup.rename(version_directory)
            raise
        shutil.rmtree(backup)
        print(f"[offline-migration] success: {version_directory}")
        return manifest
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if owns_connection:
            db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migrate legacy offline feature layout")
    parser.add_argument(
        "--version-directory",
        type=Path,
        default=Path("data/offline_store/transaction_features/v1"),
    )
    parser.add_argument("--feature-table-version", type=int, default=1)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    migrate_legacy_offline_store(
        args.version_directory,
        feature_table_version=args.feature_table_version,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
