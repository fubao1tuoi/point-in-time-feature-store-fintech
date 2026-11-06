"""Build canonical, quality-checked Silver transactions from Bronze Parquet."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq

from pit_feature_store.configuration import PipelineConfig, load_pipeline_config
from pit_feature_store.entities import (
    CARD_ADDRESS_ENTITY_PREFIX,
    CARD_ADDRESS_ENTITY_VERSION,
    CARD_ENTITY_PREFIX,
    CARD_ENTITY_VERSION,
)

SILVER_SCHEMA_VERSION = 1
SEMANTIC_FINGERPRINT_ALGORITHM = "xor64_hash_json_business_lineage_v3"
FINGERPRINT_EXCLUDED_COLUMNS = {
    "_ingestion_run_id",
    "_ingested_at_utc",
    "_identity_ingestion_run_id",
    "_identity_ingested_at_utc",
    "_silver_run_id",
    "_silver_created_at_utc",
}
DEFAULT_MANIFEST_PATH = Path("reports/generated/silver_build_manifest.json")
DEFAULT_BRONZE_MANIFEST_PATH = Path("reports/generated/bronze_ingestion_manifest.json")

BRONZE_METADATA_COLUMNS = {
    "_ingestion_run_id",
    "_source_name",
    "_source_file",
    "_source_checksum_sha256",
    "_ingested_at_utc",
    "_source_row_number",
}

STRING_COLUMNS = {
    "ProductCD",
    "card1",
    "card2",
    "card3",
    "card4",
    "card5",
    "card6",
    "addr1",
    "addr2",
    "P_emaildomain",
    "R_emaildomain",
    "DeviceType",
    "DeviceInfo",
    *(f"M{index}" for index in range(1, 10)),
    *(f"id_{index:02d}" for index in range(12, 39)),
}


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def normalize_identity_column(name: str) -> str:
    """Normalize Kaggle test identity columns such as id-01 to id_01."""
    if name.startswith("id-") and name[3:].isdigit():
        return f"id_{name[3:]}"
    return name


def silver_sql_type(column: str) -> str:
    """Return the v1 canonical type for a normalized business column."""
    if column in STRING_COLUMNS:
        return "VARCHAR"
    if column in {"TransactionID", "TransactionDT"}:
        return "BIGINT"
    if column == "isFraud":
        return "TINYINT"
    if column == "TransactionAmt":
        return "DOUBLE"
    if column.startswith(("C", "D", "V", "dist")):
        return "DOUBLE"
    if column.startswith("id_") and column[3:].isdigit():
        return "DOUBLE" if int(column[3:]) <= 11 else "VARCHAR"
    return "VARCHAR"


def _cast_expression(source_column: str, output_column: str | None = None) -> str:
    output = output_column or source_column
    source = _quote_identifier(source_column)
    alias = _quote_identifier(output)
    target_type = silver_sql_type(output)
    if target_type == "VARCHAR":
        expression = f"NULLIF({source}, '')"
    else:
        expression = f"TRY_CAST(NULLIF({source}, '') AS {target_type})"
    return f"{expression} AS {alias}"


def _canonical_code_sql(column: str) -> str:
    identifier = _quote_identifier(column)
    trimmed = f"TRIM({identifier})"
    return (
        "CASE "
        f"WHEN {identifier} IS NULL OR {trimmed} = '' THEN NULL "
        f"WHEN regexp_full_match({trimmed}, '[+-]?[0-9]+[.]0+') "
        f"THEN regexp_replace({trimmed}, '[.]0+$', '') "
        f"ELSE {trimmed} END"
    )


def entity_expressions() -> dict[str, str]:
    """SQL expressions matching the Python v1 entity ID implementations."""
    card = _canonical_code_sql("card1")
    address = _canonical_code_sql("addr1")
    card_payload = f'\'{{"card1":"\' || {card} || \'","version":1}}\''
    card_address_payload = (
        f'\'{{"addr1":"\' || {address} || \'","card1":"\' || {card} || \'","version":1}}\''
    )
    card_id = (
        f"CASE WHEN {card} IS NULL THEN NULL ELSE "
        f"'{CARD_ENTITY_PREFIX}' || sha256({card_payload}) END"
    )
    card_address_id = (
        f"CASE WHEN {card} IS NULL OR {address} IS NULL THEN NULL ELSE "
        f"'{CARD_ADDRESS_ENTITY_PREFIX}' || sha256({card_address_payload}) END"
    )
    return {
        "card_entity_id": card_id,
        "card_address_entity_id": card_address_id,
    }


def _business_columns(path: Path) -> list[str]:
    return [
        normalize_identity_column(name)
        for name in pq.ParquetFile(path).schema_arrow.names
        if name not in BRONZE_METADATA_COLUMNS
    ]


def _raw_business_columns(path: Path) -> list[str]:
    return [
        name
        for name in pq.ParquetFile(path).schema_arrow.names
        if name not in BRONZE_METADATA_COLUMNS
    ]


def _bronze_path(config: PipelineConfig, source_name: str) -> Path:
    output_name = config.sources_config.sources[source_name].bronze_output
    return config.storage_path("bronze") / output_name / "data.parquet"


def _duplicate_policy(
    connection: duckdb.DuckDBPyConnection,
    path: Path,
    key_column: str,
) -> dict[str, int | bool]:
    """Allow exact duplicate rows; reject conflicting rows sharing one key."""
    path_sql = _sql_literal(path)
    key = _quote_identifier(key_column)
    duplicate_rows = connection.execute(
        f"""
        SELECT COALESCE(SUM(row_count - 1), 0)::BIGINT
        FROM (
            SELECT COUNT(*) AS row_count
            FROM read_parquet({path_sql})
            GROUP BY {key}
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]
    if duplicate_rows == 0:
        return {
            "duplicate_excess_rows": 0,
            "exact_duplicate_rows_removed": 0,
            "conflicting_duplicate_keys": 0,
            "deduplication_required": False,
        }

    business_columns = _raw_business_columns(path)
    duplicates = connection.execute(
        f"""
        WITH duplicate_keys AS (
            SELECT {key}
            FROM read_parquet({path_sql})
            GROUP BY {key}
            HAVING COUNT(*) > 1
        )
        SELECT source.*
        FROM read_parquet({path_sql}) AS source
        INNER JOIN duplicate_keys USING ({key})
        ORDER BY {key}, _source_row_number
        """
    ).to_arrow_table()
    grouped: dict[Any, set[tuple[Any, ...]]] = defaultdict(set)
    for row in duplicates.select(business_columns).to_pylist():
        grouped[row[key_column]].add(tuple(row[column] for column in business_columns))
    conflicting = sum(len(values) > 1 for values in grouped.values())
    if conflicting:
        raise ValueError(
            f"Conflicting duplicate {key_column} values in {path.name}: {conflicting} key(s)"
        )
    return {
        "duplicate_excess_rows": int(duplicate_rows),
        "exact_duplicate_rows_removed": int(duplicate_rows),
        "conflicting_duplicate_keys": 0,
        "deduplication_required": True,
    }


def _deduplicated_source_sql(path: Path, deduplicate: bool) -> str:
    source = f"read_parquet({_sql_literal(path)})"
    if not deduplicate:
        return f"SELECT * FROM {source}"
    return (
        f"SELECT * FROM {source} "
        "QUALIFY ROW_NUMBER() OVER ("
        'PARTITION BY "TransactionID" ORDER BY _source_row_number'
        ") = 1"
    )


def _transaction_select_sql(path: Path, deduplicate: bool, split: str) -> str:
    columns = _raw_business_columns(path)
    expressions = [_cast_expression(column) for column in columns]
    if "isFraud" not in columns:
        expressions.append('CAST(NULL AS TINYINT) AS "isFraud"')
    for metadata in BRONZE_METADATA_COLUMNS:
        expressions.append(_quote_identifier(metadata))
    expressions.append(f"{_sql_literal(split)}::VARCHAR AS dataset_split")
    return (
        "SELECT\n    "
        + ",\n    ".join(expressions)
        + "\nFROM ("
        + _deduplicated_source_sql(path, deduplicate)
        + ") AS source"
    )


def _identity_select_sql(path: Path, deduplicate: bool) -> str:
    raw_columns = _raw_business_columns(path)
    expressions = [
        _cast_expression(column, normalize_identity_column(column)) for column in raw_columns
    ]
    for metadata in BRONZE_METADATA_COLUMNS:
        alias = f"_identity{metadata}"
        expressions.append(f"{_quote_identifier(metadata)} AS {_quote_identifier(alias)}")
    return (
        "SELECT\n    "
        + ",\n    ".join(expressions)
        + "\nFROM ("
        + _deduplicated_source_sql(path, deduplicate)
        + ") AS source"
    )


def _split_query(
    *,
    transaction_path: Path,
    identity_path: Path,
    split: str,
    transaction_deduplicate: bool,
    identity_deduplicate: bool,
    synthetic_epoch: datetime,
    silver_run_id: str,
    silver_created_at: datetime,
) -> str:
    transaction_sql = _transaction_select_sql(transaction_path, transaction_deduplicate, split)
    identity_sql = _identity_select_sql(identity_path, identity_deduplicate)
    entities = entity_expressions()
    epoch = synthetic_epoch.isoformat()
    created_at = silver_created_at.isoformat()
    return f"""
    WITH transactions AS (
        {transaction_sql}
    ),
    identities AS (
        {identity_sql}
    ),
    joined AS (
        SELECT
            transactions.*,
            identities.* EXCLUDE (TransactionID),
            (identities.TransactionID IS NOT NULL) AS has_identity,
            TIMESTAMPTZ {_sql_literal(epoch)}
                + transactions.TransactionDT * INTERVAL 1 SECOND AS event_time
        FROM transactions
        LEFT JOIN identities USING (TransactionID)
    ),
    entities_added AS (
        SELECT
            joined.*,
            {entities["card_entity_id"]} AS card_entity_id,
            {entities["card_address_entity_id"]} AS card_address_entity_id
        FROM joined
    )
    SELECT
        entities_added.*,
        (card_address_entity_id IS NOT NULL)::TINYINT AS has_card_address_entity,
        CASE
            WHEN card_address_entity_id IS NOT NULL THEN 'card_address'
            WHEN card_entity_id IS NOT NULL THEN 'card_only'
            ELSE 'unresolved'
        END AS entity_resolution_level,
        {CARD_ENTITY_VERSION}::SMALLINT AS card_entity_version,
        {CARD_ADDRESS_ENTITY_VERSION}::SMALLINT AS card_address_entity_version,
        CAST(event_time AS DATE) AS event_date,
        strftime(event_time, '%Y-%m') AS event_month,
        {_sql_literal(silver_run_id)}::VARCHAR AS _silver_run_id,
        TIMESTAMPTZ {_sql_literal(created_at)} AS _silver_created_at_utc,
        {SILVER_SCHEMA_VERSION}::SMALLINT AS _silver_schema_version
    FROM entities_added
    """


def _quality_metrics(
    connection: duckdb.DuckDBPyConnection,
    parquet_glob: str,
    expected_rows: dict[str, int],
    expected_identity_rows: dict[str, int],
) -> dict[str, Any]:
    source = f"read_parquet({_sql_literal(parquet_glob)}, hive_partitioning=true)"
    metrics: dict[str, Any] = {
        "row_count_by_split": {},
        "identity_matches_by_split": {},
    }
    for split in ("train", "test"):
        row_count, unique_ids, identity_matches = connection.execute(
            f"""
            SELECT
                COUNT(*)::BIGINT,
                COUNT(DISTINCT TransactionID)::BIGINT,
                COUNT(*) FILTER (WHERE has_identity)::BIGINT
            FROM {source}
            WHERE dataset_split = {_sql_literal(split)}
            """
        ).fetchone()
        metrics["row_count_by_split"][split] = row_count
        metrics["identity_matches_by_split"][split] = identity_matches
        if row_count != expected_rows[split] or unique_ids != row_count:
            raise RuntimeError(
                f"Silver row/uniqueness check failed for {split}: "
                f"rows={row_count}, unique={unique_ids}, expected={expected_rows[split]}"
            )
        if identity_matches != expected_identity_rows[split]:
            raise RuntimeError(
                f"Silver identity reconciliation failed for {split}: "
                f"matches={identity_matches}, expected={expected_identity_rows[split]}"
            )

    checks = connection.execute(
        f"""
        SELECT
            COUNT(*) FILTER (WHERE TransactionID IS NULL)::BIGINT,
            COUNT(*) FILTER (WHERE TransactionDT IS NULL OR TransactionDT < 0)::BIGINT,
            COUNT(*) FILTER (WHERE TransactionAmt IS NULL OR TransactionAmt < 0)::BIGINT,
            COUNT(*) FILTER (
                WHERE dataset_split = 'train' AND isFraud NOT IN (0, 1)
            )::BIGINT,
            COUNT(*) FILTER (WHERE event_time IS NULL)::BIGINT,
            COUNT(*) FILTER (WHERE card_entity_id IS NULL)::BIGINT,
            COUNT(*) FILTER (WHERE card_address_entity_id IS NULL)::BIGINT,
            strftime(MIN(event_time) AT TIME ZONE 'UTC', '%Y-%m-%dT%H:%M:%SZ'),
            strftime(MAX(event_time) AT TIME ZONE 'UTC', '%Y-%m-%dT%H:%M:%SZ')
        FROM {source}
        """
    ).fetchone()
    (
        metrics["null_transaction_id_count"],
        metrics["invalid_transaction_dt_count"],
        metrics["invalid_transaction_amount_count"],
        metrics["invalid_train_label_count"],
        metrics["null_event_time_count"],
        metrics["null_card_entity_count"],
        metrics["null_card_address_entity_count"],
        min_event_time,
        max_event_time,
    ) = checks
    metrics["min_event_time"] = min_event_time
    metrics["max_event_time"] = max_event_time
    invalid_counts = [
        metrics["null_transaction_id_count"],
        metrics["invalid_transaction_dt_count"],
        metrics["invalid_transaction_amount_count"],
        metrics["invalid_train_label_count"],
        metrics["null_event_time_count"],
    ]
    if any(invalid_counts):
        raise RuntimeError(f"Silver data-quality checks failed: {metrics}")
    return metrics


def _semantic_fingerprint(connection: duckdb.DuckDBPyConnection, parquet_glob: str) -> str:
    columns = connection.execute(
        f"DESCRIBE SELECT * FROM read_parquet({_sql_literal(parquet_glob)}, hive_partitioning=true)"
    ).fetchall()
    included = sorted(row[0] for row in columns if row[0] not in FINGERPRINT_EXCLUDED_COLUMNS)
    struct_fields = ", ".join(
        f"{_quote_identifier(column)} := {_quote_identifier(column)}" for column in included
    )
    xor_hash, row_count = connection.execute(
        f"""
        SELECT
            bit_xor(hash(to_json(struct_pack({struct_fields}))))::VARCHAR,
            COUNT(*)::BIGINT
        FROM read_parquet({_sql_literal(parquet_glob)}, hive_partitioning=true)
        """
    ).fetchone()
    return f"rows={row_count};xor64={xor_hash}"


def _column_fingerprints(
    connection: duckdb.DuckDBPyConnection, parquet_glob: str
) -> dict[str, str]:
    columns = connection.execute(
        f"DESCRIBE SELECT * FROM read_parquet({_sql_literal(parquet_glob)}, hive_partitioning=true)"
    ).fetchall()
    included = [row[0] for row in columns if row[0] not in FINGERPRINT_EXCLUDED_COLUMNS]
    expressions = ", ".join(
        f"bit_xor(hash({_quote_identifier(column)}))::VARCHAR AS {_quote_identifier(column)}"
        for column in included
    )
    values = connection.execute(
        f"SELECT {expressions} FROM read_parquet({_sql_literal(parquet_glob)}, "
        "hive_partitioning=true)"
    ).fetchone()
    return dict(zip(included, values, strict=True))


def _load_previous_fingerprint(manifest_path: Path) -> str | None:
    if not manifest_path.exists():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("semantic_fingerprint_algorithm") != SEMANTIC_FINGERPRINT_ALGORITHM:
        return None
    return manifest.get("semantic_fingerprint")


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _safe_publish_directory(staged: Path, final: Path, silver_root: Path) -> None:
    staged_resolved = staged.resolve()
    final_resolved = final.resolve()
    root_resolved = silver_root.resolve()
    if root_resolved not in staged_resolved.parents or root_resolved not in final_resolved.parents:
        raise RuntimeError("Refusing to publish outside the configured Silver directory")
    backup = silver_root / ".backup" / f"{final.name}_{uuid.uuid4().hex[:8]}"
    backup.parent.mkdir(parents=True, exist_ok=True)
    if final.exists():
        os.replace(final, backup)
    try:
        os.replace(staged, final)
    except Exception:
        if backup.exists() and not final.exists():
            os.replace(backup, final)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def run_silver_transformation(
    *,
    project_root: Path,
    manifest_path: Path,
    bronze_manifest_path: Path,
    memory_limit: str = "4GB",
    threads: int | None = None,
) -> dict[str, Any]:
    """Build, validate and publish the canonical partitioned Silver dataset."""
    started = datetime.now(UTC)
    run_id = f"silver_{started.strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
    config = load_pipeline_config(project_root)
    silver_root = config.storage_path("silver")
    silver_root.mkdir(parents=True, exist_ok=True)
    required = {
        name: _bronze_path(config, name)
        for name in (
            "train_transaction",
            "train_identity",
            "test_transaction",
            "test_identity",
        )
    }
    missing = [name for name, path in required.items() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing Bronze inputs: {', '.join(missing)}")

    previous_fingerprint = _load_previous_fingerprint(manifest_path)
    bronze_manifest = (
        json.loads(bronze_manifest_path.read_text(encoding="utf-8"))
        if bronze_manifest_path.exists()
        else None
    )
    connection = duckdb.connect()
    connection.execute(f"SET memory_limit = {_sql_literal(memory_limit)}")
    if threads is not None:
        if threads <= 0:
            raise ValueError("threads must be positive")
        connection.execute(f"SET threads = {threads}")
    temp_directory = silver_root / ".duckdb_tmp"
    temp_directory.mkdir(parents=True, exist_ok=True)
    connection.execute(f"SET temp_directory = {_sql_literal(temp_directory)}")
    connection.execute("SET preserve_insertion_order = false")

    print(f"[silver] run_id={run_id}", flush=True)
    print("[1/6] validating Bronze inputs and duplicate policy", flush=True)
    duplicate_metrics: dict[str, dict[str, int | bool]] = {}
    for name, path in required.items():
        duplicate_metrics[name] = _duplicate_policy(connection, path, "TransactionID")
        print(f"    [checked] {name}: {duplicate_metrics[name]}", flush=True)

    transaction_rows = {
        split: connection.execute(
            f"SELECT COUNT(*) FROM read_parquet({_sql_literal(required[f'{split}_transaction'])})"
        ).fetchone()[0]
        - int(duplicate_metrics[f"{split}_transaction"]["exact_duplicate_rows_removed"])
        for split in ("train", "test")
    }
    identity_rows = {
        split: connection.execute(
            f"SELECT COUNT(*) FROM read_parquet({_sql_literal(required[f'{split}_identity'])})"
        ).fetchone()[0]
        - int(duplicate_metrics[f"{split}_identity"]["exact_duplicate_rows_removed"])
        for split in ("train", "test")
    }

    print("[2/6] building canonical cast/join/entity SQL", flush=True)
    train_query = _split_query(
        transaction_path=required["train_transaction"],
        identity_path=required["train_identity"],
        split="train",
        transaction_deduplicate=bool(
            duplicate_metrics["train_transaction"]["deduplication_required"]
        ),
        identity_deduplicate=bool(duplicate_metrics["train_identity"]["deduplication_required"]),
        synthetic_epoch=config.project_config.project.synthetic_epoch,
        silver_run_id=run_id,
        silver_created_at=started,
    )
    test_query = _split_query(
        transaction_path=required["test_transaction"],
        identity_path=required["test_identity"],
        split="test",
        transaction_deduplicate=bool(
            duplicate_metrics["test_transaction"]["deduplication_required"]
        ),
        identity_deduplicate=bool(duplicate_metrics["test_identity"]["deduplication_required"]),
        synthetic_epoch=config.project_config.project.synthetic_epoch,
        silver_run_id=run_id,
        silver_created_at=started,
    )
    combined_query = f"({train_query}) UNION ALL BY NAME ({test_query})"

    staging_parent = silver_root / ".staging"
    staging_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"{run_id}_", dir=staging_parent) as temp_dir:
        staged_output = Path(temp_dir) / "transactions"
        staged_output.mkdir(parents=True, exist_ok=True)
        print("[3/6] writing partitioned Silver Parquet", flush=True)
        copy_started = time.perf_counter()
        connection.execute(
            f"""
            COPY ({combined_query})
            TO {_sql_literal(staged_output)}
            (
                FORMAT PARQUET,
                COMPRESSION ZSTD,
                PARTITION_BY (dataset_split, event_month),
                ROW_GROUP_SIZE 100000,
                OVERWRITE_OR_IGNORE true
            )
            """
        )
        print(f"    [written] {time.perf_counter() - copy_started:.1f}s", flush=True)

        parquet_glob = str(staged_output / "**" / "*.parquet")
        print("[4/6] running row, join, type and event-time quality checks", flush=True)
        quality = _quality_metrics(connection, parquet_glob, transaction_rows, identity_rows)
        fingerprint = _semantic_fingerprint(connection, parquet_glob)
        matches_previous = (
            None if previous_fingerprint is None else fingerprint == previous_fingerprint
        )
        if matches_previous is False:
            final_glob = str(silver_root / "transactions" / "**" / "*.parquet")
            previous_columns = _column_fingerprints(connection, final_glob)
            current_columns = _column_fingerprints(connection, parquet_glob)
            changed_columns = [
                column
                for column in previous_columns
                if previous_columns[column] != current_columns.get(column)
            ]
            raise RuntimeError(
                "Silver semantic fingerprint changed although a previous manifest exists: "
                f"previous={previous_fingerprint}, current={fingerprint}. "
                f"Changed columns: {changed_columns[:30]}. "
                "Review source/config changes before publishing"
            )
        print(f"    [quality-pass] semantic_fingerprint={fingerprint}", flush=True)
        print("[5/6] publishing canonical Silver dataset", flush=True)
        connection.close()
        final_output = silver_root / "transactions"
        _safe_publish_directory(staged_output, final_output, silver_root)

    output_files = list((silver_root / "transactions").rglob("*.parquet"))
    completed = datetime.now(UTC)
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "status": "success",
        "silver_schema_version": SILVER_SCHEMA_VERSION,
        "started_at_utc": started.isoformat(),
        "completed_at_utc": completed.isoformat(),
        "duration_seconds": round((completed - started).total_seconds(), 3),
        "synthetic_epoch": config.project_config.project.synthetic_epoch.isoformat(),
        "bronze_run_id": bronze_manifest.get("run_id") if bronze_manifest else None,
        "output_path": str(silver_root / "transactions"),
        "partition_columns": ["dataset_split", "event_month"],
        "parquet_file_count": len(output_files),
        "output_size_bytes": sum(path.stat().st_size for path in output_files),
        "duplicate_policy": duplicate_metrics,
        "quality_metrics": quality,
        "semantic_fingerprint_algorithm": SEMANTIC_FINGERPRINT_ALGORITHM,
        "semantic_fingerprint": fingerprint,
        "previous_semantic_fingerprint": previous_fingerprint,
        "matches_previous_run": matches_previous,
    }
    _write_manifest(manifest_path, manifest)
    print(f"[6/6] success: manifest={manifest_path}", flush=True)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument(
        "--bronze-manifest",
        type=Path,
        default=DEFAULT_BRONZE_MANIFEST_PATH,
    )
    parser.add_argument("--memory-limit", default="4GB")
    parser.add_argument("--threads", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.project_root.resolve()

    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    run_silver_transformation(
        project_root=root,
        manifest_path=resolve(args.manifest),
        bronze_manifest_path=resolve(args.bronze_manifest),
        memory_limit=args.memory_limit,
        threads=args.threads,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
