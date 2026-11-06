"""Streaming, atomic Raw-to-Bronze ingestion for IEEE-CIS CSV sources."""

from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from pit_feature_store.configuration import PipelineConfig, SourceDefinition, load_pipeline_config
from pit_feature_store.profiling import sha256_file

DEFAULT_MANIFEST_PATH = Path("reports/generated/bronze_ingestion_manifest.json")
DEFAULT_BLOCK_SIZE_MB = 32
DEFAULT_ROW_GROUP_SIZE = 100_000
DEFAULT_PROGRESS_EVERY_ROWS = 100_000

BRONZE_METADATA_COLUMNS = (
    "_ingestion_run_id",
    "_source_name",
    "_source_file",
    "_source_checksum_sha256",
    "_ingested_at_utc",
    "_source_row_number",
)


@dataclass(frozen=True)
class BronzeSourceResult:
    """Machine-readable result for one ingested source."""

    source_name: str
    source_file: str
    source_path: str
    source_size_bytes: int
    source_checksum_sha256: str
    source_column_count: int
    bronze_column_count: int
    row_count: int
    output_path: str
    output_size_bytes: int
    duration_seconds: float


def _read_csv_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        try:
            header = next(csv.reader(handle))
        except StopIteration as error:
            raise ValueError(f"CSV source is empty: {path}") from error
    if not header or any(not column for column in header):
        raise ValueError(f"CSV source has an invalid header: {path}")
    if len(header) != len(set(header)):
        raise ValueError(f"CSV source has duplicate column names: {path}")
    return header


def _validate_source_header(
    source_name: str,
    definition: SourceDefinition,
    header: list[str],
) -> None:
    missing = sorted(set(definition.required_columns) - set(header))
    if missing:
        raise ValueError(
            f"Source '{source_name}' is missing required columns: {', '.join(missing)}"
        )
    collisions = sorted(set(header) & set(BRONZE_METADATA_COLUMNS))
    if collisions:
        raise ValueError(
            f"Source '{source_name}' collides with Bronze metadata columns: {', '.join(collisions)}"
        )


def _open_lexical_csv_reader(path: Path, header: list[str], block_size_bytes: int):
    """Read all source cells as strings so Bronze does not cast business values."""
    return pacsv.open_csv(
        path,
        read_options=pacsv.ReadOptions(
            block_size=block_size_bytes,
            column_names=header,
            skip_rows=1,
            use_threads=True,
        ),
        parse_options=pacsv.ParseOptions(delimiter=","),
        convert_options=pacsv.ConvertOptions(
            column_types={column: pa.string() for column in header},
            strings_can_be_null=False,
            check_utf8=True,
        ),
    )


def _enrich_batch(
    batch: pa.RecordBatch,
    *,
    run_id: str,
    source_name: str,
    source_file: str,
    source_checksum: str,
    ingested_at: datetime,
    first_row_number: int,
) -> pa.RecordBatch:
    row_count = batch.num_rows
    metadata_arrays = [
        pa.array([run_id] * row_count, type=pa.string()),
        pa.array([source_name] * row_count, type=pa.string()),
        pa.array([source_file] * row_count, type=pa.string()),
        pa.array([source_checksum] * row_count, type=pa.string()),
        pa.array([ingested_at] * row_count, type=pa.timestamp("us", tz="UTC")),
        pa.array(
            range(first_row_number, first_row_number + row_count),
            type=pa.int64(),
        ),
    ]
    return pa.RecordBatch.from_arrays(
        [*batch.columns, *metadata_arrays],
        names=[*batch.schema.names, *BRONZE_METADATA_COLUMNS],
    )


def ingest_source_to_staging(
    *,
    source_name: str,
    definition: SourceDefinition,
    source_path: Path,
    staging_path: Path,
    run_id: str,
    ingested_at: datetime,
    block_size_mb: int = DEFAULT_BLOCK_SIZE_MB,
    row_group_size: int = DEFAULT_ROW_GROUP_SIZE,
    progress_every_rows: int = DEFAULT_PROGRESS_EVERY_ROWS,
) -> BronzeSourceResult:
    """Stream one CSV to a staged Parquet file and validate its metadata."""
    if block_size_mb <= 0 or row_group_size <= 0 or progress_every_rows <= 0:
        raise ValueError("block size, row group size and progress interval must be positive")
    if not source_path.exists():
        raise FileNotFoundError(f"Missing source '{source_name}': {source_path}")

    started = time.perf_counter()
    header = _read_csv_header(source_path)
    _validate_source_header(source_name, definition, header)
    checksum = sha256_file(source_path)
    reader = _open_lexical_csv_reader(source_path, header, block_size_mb * 1024 * 1024)

    staging_path.parent.mkdir(parents=True, exist_ok=True)
    writer: pq.ParquetWriter | None = None
    row_count = 0
    next_progress = progress_every_rows
    try:
        for batch in reader:
            enriched = _enrich_batch(
                batch,
                run_id=run_id,
                source_name=source_name,
                source_file=source_path.name,
                source_checksum=checksum,
                ingested_at=ingested_at,
                first_row_number=row_count + 1,
            )
            if writer is None:
                writer = pq.ParquetWriter(
                    staging_path,
                    enriched.schema,
                    compression="zstd",
                    use_dictionary=True,
                )
            writer.write_batch(enriched, row_group_size=row_group_size)
            row_count += batch.num_rows
            if row_count >= next_progress:
                elapsed = time.perf_counter() - started
                print(
                    f"    [progress] {source_name}: {row_count:,} rows ({elapsed:.1f}s)",
                    flush=True,
                )
                while next_progress <= row_count:
                    next_progress += progress_every_rows
    finally:
        if writer is not None:
            writer.close()

    if writer is None:
        raise ValueError(f"Source '{source_name}' contains no data rows")

    parquet_file = pq.ParquetFile(staging_path)
    output_rows = parquet_file.metadata.num_rows
    expected_columns = len(header) + len(BRONZE_METADATA_COLUMNS)
    output_columns = len(parquet_file.schema_arrow)
    if output_rows != row_count:
        raise RuntimeError(
            f"Bronze row reconciliation failed for '{source_name}': "
            f"read={row_count}, parquet={output_rows}"
        )
    if output_columns != expected_columns:
        raise RuntimeError(
            f"Bronze schema reconciliation failed for '{source_name}': "
            f"expected={expected_columns}, parquet={output_columns}"
        )

    duration = time.perf_counter() - started
    return BronzeSourceResult(
        source_name=source_name,
        source_file=source_path.name,
        source_path=str(source_path),
        source_size_bytes=source_path.stat().st_size,
        source_checksum_sha256=checksum,
        source_column_count=len(header),
        bronze_column_count=output_columns,
        row_count=row_count,
        output_path="",
        output_size_bytes=staging_path.stat().st_size,
        duration_seconds=round(duration, 3),
    )


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary_path, path)


def run_bronze_ingestion(
    *,
    project_root: Path,
    manifest_path: Path,
    source_names: list[str] | None = None,
    block_size_mb: int = DEFAULT_BLOCK_SIZE_MB,
    row_group_size: int = DEFAULT_ROW_GROUP_SIZE,
    progress_every_rows: int = DEFAULT_PROGRESS_EVERY_ROWS,
) -> dict[str, Any]:
    """Stage all requested sources, validate them, then publish atomically per file."""
    config: PipelineConfig = load_pipeline_config(project_root)
    definitions = config.sources_config.sources
    selected = source_names or list(definitions)
    unknown = sorted(set(selected) - set(definitions))
    if unknown:
        raise ValueError(f"Unknown source names: {', '.join(unknown)}")

    bronze_root = config.storage_path("bronze")
    bronze_root.mkdir(parents=True, exist_ok=True)
    staging_root = bronze_root / ".staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    run_id = f"bronze_{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
    started_at = datetime.now(UTC)
    results: list[BronzeSourceResult] = []

    print(f"[bronze] run_id={run_id}", flush=True)
    print(f"[bronze] sources={', '.join(selected)}", flush=True)
    with tempfile.TemporaryDirectory(prefix=f"{run_id}_", dir=staging_root) as temp_dir:
        temporary_root = Path(temp_dir)
        for index, source_name in enumerate(selected, start=1):
            definition = definitions[source_name]
            source_path = config.source_path(source_name)
            staged_path = temporary_root / f"{definition.bronze_output}.parquet"
            print(
                f"[{index}/{len(selected)}] ingest {source_name}: {source_path.name}",
                flush=True,
            )
            result = ingest_source_to_staging(
                source_name=source_name,
                definition=definition,
                source_path=source_path,
                staging_path=staged_path,
                run_id=run_id,
                ingested_at=started_at,
                block_size_mb=block_size_mb,
                row_group_size=row_group_size,
                progress_every_rows=progress_every_rows,
            )
            final_path = bronze_root / definition.bronze_output / "data.parquet"
            result = BronzeSourceResult(
                **{
                    **asdict(result),
                    "output_path": str(final_path),
                }
            )
            results.append(result)
            print(
                f"    [validated] {result.row_count:,} rows, "
                f"{result.bronze_column_count} columns, "
                f"{result.output_size_bytes / 1024 / 1024:.2f} MB",
                flush=True,
            )

        print("[bronze] validation passed; publishing staged files", flush=True)
        for source_name, result in zip(selected, results, strict=True):
            definition = definitions[source_name]
            staged_path = temporary_root / f"{definition.bronze_output}.parquet"
            final_path = Path(result.output_path)
            final_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged_path, final_path)

    completed_at = datetime.now(UTC)
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "status": "success",
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": completed_at.isoformat(),
        "duration_seconds": round((completed_at - started_at).total_seconds(), 3),
        "source_config_version": config.sources_config.version,
        "preservation_policy": {
            "raw_columns": "stored as UTF-8 strings without type casting",
            "empty_fields": "preserved as empty strings",
            "source_order": "preserved with _source_row_number starting at 1",
        },
        "metadata_columns": list(BRONZE_METADATA_COLUMNS),
        "sources": [asdict(result) for result in results],
    }
    _write_manifest(manifest_path, manifest)
    print(f"[bronze] success: manifest={manifest_path}", flush=True)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument(
        "--sources",
        nargs="+",
        help="Optional source names; defaults to every source in configs/sources.yaml.",
    )
    parser.add_argument("--block-size-mb", type=int, default=DEFAULT_BLOCK_SIZE_MB)
    parser.add_argument("--row-group-size", type=int, default=DEFAULT_ROW_GROUP_SIZE)
    parser.add_argument(
        "--progress-every-rows",
        type=int,
        default=DEFAULT_PROGRESS_EVERY_ROWS,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root = args.project_root.resolve()
    manifest_path = args.manifest
    if not manifest_path.is_absolute():
        manifest_path = project_root / manifest_path
    run_bronze_ingestion(
        project_root=project_root,
        manifest_path=manifest_path,
        source_names=args.sources,
        block_size_mb=args.block_size_mb,
        row_group_size=args.row_group_size,
        progress_every_rows=args.progress_every_rows,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
