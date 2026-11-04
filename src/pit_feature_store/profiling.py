"""Streaming inventory and profiling for the IEEE-CIS Fraud Detection dataset."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import time
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import yaml

DEFAULT_SOURCE_CONFIG = Path("configs/sources.yaml")
DEFAULT_JSON_REPORT = Path("reports/generated/dataset_profile.json")
DEFAULT_MARKDOWN_REPORT = Path("reports/dataset_audit_summary.md")
DEFAULT_CHECKSUM_MANIFEST = Path("reports/generated/raw_checksums.json")
SECONDS_PER_DAY = 86_400
CHECKSUM_CHUNK_SIZE = 8 * 1024 * 1024

SELECTED_CARDINALITY_COLUMNS = {
    "TransactionID",
    "isFraud",
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
}

TOP_VALUE_COLUMNS = {
    "isFraud",
    "ProductCD",
    "card4",
    "card6",
    "P_emaildomain",
    "R_emaildomain",
    "DeviceType",
}


def _json_safe(value: Any) -> Any:
    """Convert Arrow/Python scalar values into JSON-compatible values."""
    if value is None:
        return None
    if isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "as_py"):
        return _json_safe(value.as_py())
    return str(value)


def _scalar(array: pa.Array, operation: str) -> Any:
    function = getattr(pc, operation)
    result = function(array, skip_nulls=True)
    return None if result is None else result.as_py()


def _iter_non_null(array: pa.Array) -> Iterable[Any]:
    for value in array.to_pylist():
        if value is not None:
            yield value


def _read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return next(csv.reader(handle))


def sha256_file(path: Path, *, chunk_size: int = CHECKSUM_CHUNK_SIZE) -> str:
    """Return a SHA-256 digest while keeping memory usage bounded."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def build_checksum_manifest(sources: dict[str, Path]) -> dict[str, Any]:
    """Build a deterministic content manifest for configured raw sources."""
    files = []
    for source_name, path in sources.items():
        if not path.exists():
            raise FileNotFoundError(f"Missing source '{source_name}': {path}")
        files.append(
            {
                "source_name": source_name,
                "file_name": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "algorithm": "sha256",
        "files": files,
    }


def _new_reader(path: Path, block_size: int) -> pacsv.CSVStreamingReader:
    return pacsv.open_csv(
        path,
        read_options=pacsv.ReadOptions(block_size=block_size, use_threads=True),
        parse_options=pacsv.ParseOptions(delimiter=","),
        convert_options=pacsv.ConvertOptions(
            strings_can_be_null=True,
            null_values=["", "NA", "NaN", "nan", "null", "NULL"],
        ),
    )


@dataclass
class ColumnAccumulator:
    """Memory-bounded statistics for one column."""

    name: str
    dtype: str
    null_count: int = 0
    non_null_count: int = 0
    min_value: Any = None
    max_value: Any = None
    low_cardinality_values: set[Any] = field(default_factory=set)
    cardinality_exceeded: bool = False
    exact_values: set[Any] | None = None
    top_values: Counter[Any] | None = None

    def update(self, array: pa.Array, low_cardinality_limit: int) -> None:
        self.null_count += array.null_count
        self.non_null_count += len(array) - array.null_count

        if pa.types.is_integer(array.type) or pa.types.is_floating(array.type):
            batch_min = _scalar(array, "min")
            batch_max = _scalar(array, "max")
            if batch_min is not None:
                self.min_value = (
                    batch_min if self.min_value is None else min(self.min_value, batch_min)
                )
            if batch_max is not None:
                self.max_value = (
                    batch_max if self.max_value is None else max(self.max_value, batch_max)
                )

        values: list[Any] | None = None
        if (
            self.exact_values is not None
            or self.top_values is not None
            or not self.cardinality_exceeded
        ):
            values = list(_iter_non_null(array))

        if self.exact_values is not None and values is not None:
            self.exact_values.update(values)

        if self.top_values is not None and values is not None:
            self.top_values.update(values)

        if not self.cardinality_exceeded and values is not None:
            self.low_cardinality_values.update(values)
            if len(self.low_cardinality_values) > low_cardinality_limit:
                self.cardinality_exceeded = True
                self.low_cardinality_values.clear()

    def to_dict(self, row_count: int, top_n: int) -> dict[str, Any]:
        if self.exact_values is not None:
            cardinality: int | str | None = len(self.exact_values)
        elif self.cardinality_exceeded:
            cardinality = None
        else:
            cardinality = len(self.low_cardinality_values)

        top_values = []
        if self.top_values is not None:
            top_values = [
                {"value": _json_safe(value), "count": count}
                for value, count in self.top_values.most_common(top_n)
            ]

        return {
            "dtype": self.dtype,
            "null_count": self.null_count,
            "null_pct": round(100 * self.null_count / row_count, 4) if row_count else 0.0,
            "non_null_count": self.non_null_count,
            "cardinality": cardinality,
            "cardinality_is_exact": self.exact_values is not None or not self.cardinality_exceeded,
            "min": _json_safe(self.min_value),
            "max": _json_safe(self.max_value),
            "top_values": top_values,
        }


def profile_csv(
    path: Path,
    *,
    block_size: int = 64 * 1024 * 1024,
    low_cardinality_limit: int = 100,
    top_n: int = 10,
) -> dict[str, Any]:
    """Profile a CSV in record batches to keep memory use bounded."""
    started = time.perf_counter()
    reader = _new_reader(path, block_size)
    schema = reader.schema
    accumulators: dict[str, ColumnAccumulator] = {}
    for field_ in schema:
        accumulators[field_.name] = ColumnAccumulator(
            name=field_.name,
            dtype=str(field_.type),
            exact_values=set() if field_.name in SELECTED_CARDINALITY_COLUMNS else None,
            top_values=Counter() if field_.name in TOP_VALUE_COLUMNS else None,
        )

    row_count = 0
    transaction_ids: set[Any] = set()
    duplicate_transaction_ids = 0
    transaction_dt_monotonic = True
    previous_transaction_dt: Any = None
    negative_amount_count = 0
    negative_time_count = 0
    day_profile: dict[int, dict[str, float | int]] = defaultdict(
        lambda: {"transactions": 0, "frauds": 0, "amount_sum": 0.0}
    )

    for batch in reader:
        row_count += batch.num_rows
        for name, accumulator in accumulators.items():
            accumulator.update(
                batch.column(batch.schema.get_field_index(name)), low_cardinality_limit
            )

        names = set(batch.schema.names)
        if "TransactionID" in names:
            for value in _iter_non_null(
                batch.column(batch.schema.get_field_index("TransactionID"))
            ):
                if value in transaction_ids:
                    duplicate_transaction_ids += 1
                transaction_ids.add(value)

        if "TransactionDT" in names:
            dt_array = batch.column(batch.schema.get_field_index("TransactionDT"))
            dt_values = list(_iter_non_null(dt_array))
            negative_time_count += sum(value < 0 for value in dt_values)
            if dt_values:
                if previous_transaction_dt is not None and dt_values[0] < previous_transaction_dt:
                    transaction_dt_monotonic = False
                if any(
                    current < previous
                    for previous, current in zip(dt_values, dt_values[1:], strict=False)
                ):
                    transaction_dt_monotonic = False
                previous_transaction_dt = dt_values[-1]

            fraud_values = (
                batch.column(batch.schema.get_field_index("isFraud")).to_pylist()
                if "isFraud" in names
                else [None] * batch.num_rows
            )
            amount_values = (
                batch.column(batch.schema.get_field_index("TransactionAmt")).to_pylist()
                if "TransactionAmt" in names
                else [None] * batch.num_rows
            )
            for dt_value, fraud, amount in zip(
                dt_array.to_pylist(), fraud_values, amount_values, strict=False
            ):
                if dt_value is None:
                    continue
                day = int(dt_value // SECONDS_PER_DAY)
                day_profile[day]["transactions"] += 1
                day_profile[day]["frauds"] += int(fraud or 0)
                day_profile[day]["amount_sum"] += float(amount or 0.0)

        if "TransactionAmt" in names:
            amount_array = batch.column(batch.schema.get_field_index("TransactionAmt"))
            negative_amount_count += sum(value < 0 for value in _iter_non_null(amount_array))

    columns = {
        name: accumulator.to_dict(row_count, top_n) for name, accumulator in accumulators.items()
    }
    day_rows = []
    for day, values in sorted(day_profile.items()):
        transactions = int(values["transactions"])
        frauds = int(values["frauds"])
        day_rows.append(
            {
                "relative_day": day,
                "transactions": transactions,
                "frauds": frauds,
                "fraud_rate": round(frauds / transactions, 8) if transactions else None,
                "amount_sum": round(float(values["amount_sum"]), 4),
                "amount_avg": round(float(values["amount_sum"]) / transactions, 4)
                if transactions
                else None,
            }
        )

    return {
        "path": str(path),
        "file_name": path.name,
        "file_size_bytes": path.stat().st_size,
        "row_count": row_count,
        "column_count": len(schema),
        "header": _read_header(path),
        "schema": {field_.name: str(field_.type) for field_ in schema},
        "columns": columns,
        "checks": {
            "transaction_id_null_count": columns.get("TransactionID", {}).get("null_count"),
            "transaction_id_unique_count": len(transaction_ids) if transaction_ids else None,
            "duplicate_transaction_id_count": duplicate_transaction_ids,
            "transaction_dt_monotonic_non_decreasing": transaction_dt_monotonic
            if "TransactionDT" in columns
            else None,
            "negative_transaction_dt_count": negative_time_count
            if "TransactionDT" in columns
            else None,
            "negative_transaction_amount_count": negative_amount_count
            if "TransactionAmt" in columns
            else None,
        },
        "relative_day_profile": day_rows,
        "profile_duration_seconds": round(time.perf_counter() - started, 3),
    }


def load_sources(config_path: Path, project_root: Path) -> dict[str, Path]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    sources = {}
    for source_name, definition in config["sources"].items():
        path = Path(definition["path"])
        sources[source_name] = path if path.is_absolute() else project_root / path
    return sources


def _identity_coverage(transaction: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
    transaction_ids = transaction["columns"].get("TransactionID", {}).get("cardinality")
    identity_ids = identity["columns"].get("TransactionID", {}).get("cardinality")
    identity_rows = identity["row_count"]
    transaction_rows = transaction["row_count"]
    return {
        "transaction_rows": transaction_rows,
        "identity_rows": identity_rows,
        "transaction_id_cardinality": transaction_ids,
        "identity_id_cardinality": identity_ids,
        "identity_row_coverage_pct": round(100 * identity_rows / transaction_rows, 4)
        if transaction_rows
        else None,
        "note": (
            "Coverage uses row counts; join integrity is checked through key null/duplicate checks."
        ),
    }


def build_report(profiles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    report: dict[str, Any] = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "dataset": "IEEE-CIS Fraud Detection",
        "profiles": profiles,
    }
    for split in ("train", "test"):
        transaction_name = f"{split}_transaction"
        identity_name = f"{split}_identity"
        if transaction_name in profiles and identity_name in profiles:
            report[f"{split}_identity_coverage"] = _identity_coverage(
                profiles[transaction_name], profiles[identity_name]
            )
    for table in ("transaction", "identity"):
        train_name = f"train_{table}"
        test_name = f"test_{table}"
        if train_name in profiles and test_name in profiles:
            train_columns = set(profiles[train_name]["header"])
            test_columns = set(profiles[test_name]["header"])
            expected_train_only = {"isFraud"} if table == "transaction" else set()
            report[f"{table}_schema_comparison"] = {
                "train_only_columns": sorted(train_columns - test_columns),
                "test_only_columns": sorted(test_columns - train_columns),
                "expected_train_only_columns": sorted(expected_train_only),
                "unexpected_train_only_columns": sorted(
                    (train_columns - test_columns) - expected_train_only
                ),
                "schemas_compatible": not (
                    ((train_columns - test_columns) - expected_train_only)
                    or (test_columns - train_columns)
                ),
            }
    return report


def _fmt_int(value: Any) -> str:
    return "—" if value is None else f"{int(value):,}"


def _fmt_pct(value: Any) -> str:
    return "—" if value is None else f"{float(value):.4f}%"


def render_markdown(report: dict[str, Any]) -> str:
    profiles = report["profiles"]
    lines = [
        "# IEEE-CIS Dataset Audit Summary",
        "",
        f"> Sinh tự động lúc `{report['generated_at_utc']}` bởi `profile-ieee-cis`.",
        "",
        "## 1. Dataset inventory",
        "",
        "| Source | Rows | Columns | Size (MB) | Runtime (s) |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, profile in profiles.items():
        lines.append(
            f"| `{name}` | {_fmt_int(profile['row_count'])} | "
            f"{_fmt_int(profile['column_count'])} | "
            f"{profile['file_size_bytes'] / 1024 / 1024:.2f} | "
            f"{profile['profile_duration_seconds']:.2f} |"
        )

    lines.extend(["", "## 2. Data integrity checks", ""])
    for name, profile in profiles.items():
        checks = profile["checks"]
        lines.extend(
            [
                f"### `{name}`",
                "",
                f"- Null `TransactionID`: {_fmt_int(checks['transaction_id_null_count'])}",
                f"- Unique `TransactionID`: {_fmt_int(checks['transaction_id_unique_count'])}",
                (
                    "- Duplicate `TransactionID`: "
                    f"{_fmt_int(checks['duplicate_transaction_id_count'])}"
                ),
                f"- `TransactionDT` monotonic: {checks['transaction_dt_monotonic_non_decreasing']}",
                f"- Negative `TransactionDT`: {_fmt_int(checks['negative_transaction_dt_count'])}",
                (
                    "- Negative `TransactionAmt`: "
                    f"{_fmt_int(checks['negative_transaction_amount_count'])}"
                ),
                "",
            ]
        )

    lines.extend(["## 3. Target and temporal profile", ""])
    train = profiles.get("train_transaction")
    if train:
        fraud = train["columns"].get("isFraud", {})
        top = {str(item["value"]): item["count"] for item in fraud.get("top_values", [])}
        fraud_count = top.get("1", 0)
        non_fraud_count = top.get("0", 0)
        fraud_rate = 100 * fraud_count / train["row_count"] if train["row_count"] else 0
        dt = train["columns"].get("TransactionDT", {})
        amount = train["columns"].get("TransactionAmt", {})
        lines.extend(
            [
                f"- Fraud: {_fmt_int(fraud_count)} ({fraud_rate:.4f}%)",
                f"- Non-fraud: {_fmt_int(non_fraud_count)}",
                f"- `TransactionDT` range: `{dt.get('min')}` → `{dt.get('max')}`",
                f"- Relative days represented: {_fmt_int(len(train['relative_day_profile']))}",
                f"- `TransactionAmt` range: `{amount.get('min')}` → `{amount.get('max')}`",
                "",
            ]
        )

    lines.extend(["## 4. Identity coverage", ""])
    for split in ("train", "test"):
        coverage = report.get(f"{split}_identity_coverage")
        if coverage:
            lines.append(
                f"- **{split.title()}**: {_fmt_int(coverage['identity_rows'])}/"
                f"{_fmt_int(coverage['transaction_rows'])} rows "
                f"({_fmt_pct(coverage['identity_row_coverage_pct'])})."
            )

    lines.extend(["", "## 5. Train/test schema comparison", ""])
    for table in ("transaction", "identity"):
        comparison = report.get(f"{table}_schema_comparison")
        if not comparison:
            continue
        lines.extend(
            [
                f"### `{table}`",
                "",
                (
                    "- Compatible after expected target removal: "
                    f"**{comparison['schemas_compatible']}**."
                ),
                (
                    "- Train-only columns: "
                    + (", ".join(f"`{x}`" for x in comparison["train_only_columns"]) or "none")
                    + "."
                ),
                (
                    "- Test-only columns: "
                    + (", ".join(f"`{x}`" for x in comparison["test_only_columns"]) or "none")
                    + "."
                ),
                "",
            ]
        )

    lines.extend(["## 6. Missing-data highlights", ""])
    for name, profile in profiles.items():
        high_missing = sorted(
            (
                (column, stats["null_pct"])
                for column, stats in profile["columns"].items()
                if stats["null_pct"] >= 90
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        lines.append(f"### `{name}`")
        lines.append("")
        lines.append(f"- Columns with at least 90% missing values: **{len(high_missing)}**.")
        if high_missing:
            preview = ", ".join(f"`{column}` ({pct:.2f}%)" for column, pct in high_missing[:20])
            lines.append(f"- Highest missing columns: {preview}.")
        lines.append("")

    lines.extend(
        [
            "## 7. Selected cardinalities",
            "",
            "| Source | Column | Cardinality | Null % |",
            "|---|---|---:|---:|",
        ]
    )
    for name, profile in profiles.items():
        for column in sorted(SELECTED_CARDINALITY_COLUMNS):
            stats = profile["columns"].get(column)
            if stats:
                lines.append(
                    f"| `{name}` | `{column}` | {_fmt_int(stats['cardinality'])} | "
                    f"{stats['null_pct']:.4f}% |"
                )

    lines.extend(
        [
            "",
            "## 8. Initial findings for the PIT Feature Store",
            "",
            (
                "- `TransactionDT` is a relative time offset, not a real timestamp. "
                "The project must use a documented synthetic epoch."
            ),
            (
                "- Identity data exists for only part of the transactions, so "
                "transaction-to-identity enrichment must use a left join."
            ),
            (
                "- The dataset has no official customer identifier. A surrogate entity "
                "key must be evaluated separately before rolling features are finalized."
            ),
            (
                "- The target is imbalanced; chronological evaluation and PR-AUC are "
                "required in addition to ROC-AUC."
            ),
            (
                "- Columns with opaque semantics should not be the only evidence of "
                "point-in-time correctness."
            ),
            "",
            "## 9. Generated artifacts",
            "",
            "- Full machine-readable profile: `reports/generated/dataset_profile.json`.",
            "- Raw-file SHA-256 manifest: `reports/generated/raw_checksums.json`.",
            "- This summary: `reports/dataset_audit_summary.md`.",
            "",
        ]
    )
    return "\n".join(lines)


def run_profile(
    *,
    project_root: Path,
    source_config: Path,
    json_output: Path,
    markdown_output: Path,
    checksum_output: Path = DEFAULT_CHECKSUM_MANIFEST,
    source_names: list[str] | None = None,
    block_size_mb: int = 64,
) -> dict[str, Any]:
    sources = load_sources(source_config, project_root)
    selected_sources = source_names or list(sources)
    unknown = sorted(set(selected_sources) - set(sources))
    if unknown:
        raise ValueError(f"Unknown source names: {', '.join(unknown)}")

    selected_source_paths = {name: sources[name] for name in selected_sources}
    print(f"[checksum] hashing {len(selected_source_paths)} raw file(s)", flush=True)
    checksum_manifest = build_checksum_manifest(selected_source_paths)
    checksum_output.parent.mkdir(parents=True, exist_ok=True)
    checksum_output.write_text(
        json.dumps(checksum_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    profiles = {}
    for name in selected_sources:
        path = sources[name]
        if not path.exists():
            raise FileNotFoundError(f"Missing source '{name}': {path}")
        print(f"[profile] {name}: {path.name}", flush=True)
        profiles[name] = profile_csv(path, block_size=block_size_mb * 1024 * 1024)
        print(
            f"[done] {name}: {profiles[name]['row_count']:,} rows in "
            f"{profiles[name]['profile_duration_seconds']:.2f}s",
            flush=True,
        )

    report = build_report(profiles)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_output.write_text(render_markdown(report), encoding="utf-8")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--source-config", type=Path, default=DEFAULT_SOURCE_CONFIG)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_REPORT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_REPORT)
    parser.add_argument("--checksum-output", type=Path, default=DEFAULT_CHECKSUM_MANIFEST)
    parser.add_argument(
        "--sources",
        nargs="+",
        help="Optional source names from configs/sources.yaml; defaults to all sources.",
    )
    parser.add_argument("--block-size-mb", type=int, default=64)
    parser.add_argument(
        "--reuse-existing-json",
        action="store_true",
        help="Regenerate reports from an existing JSON profile without scanning CSV files again.",
    )
    parser.add_argument(
        "--checksum-only",
        action="store_true",
        help="Only regenerate the raw-file checksum manifest; skip dataset profiling.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root = args.project_root.resolve()

    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else project_root / path

    json_output = resolve(args.json_output)
    markdown_output = resolve(args.markdown_output)
    checksum_output = resolve(args.checksum_output)
    if args.checksum_only:
        sources = load_sources(resolve(args.source_config), project_root)
        selected_sources = args.sources or list(sources)
        unknown = sorted(set(selected_sources) - set(sources))
        if unknown:
            raise ValueError(f"Unknown source names: {', '.join(unknown)}")
        manifest = build_checksum_manifest({name: sources[name] for name in selected_sources})
        checksum_output.parent.mkdir(parents=True, exist_ok=True)
        checksum_output.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[checksum] wrote {len(manifest['files'])} file(s) to {checksum_output}")
    elif args.reuse_existing_json:
        existing = json.loads(json_output.read_text(encoding="utf-8"))
        report = build_report(existing["profiles"])
        json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_output.write_text(render_markdown(report), encoding="utf-8")
    else:
        run_profile(
            project_root=project_root,
            source_config=resolve(args.source_config),
            json_output=json_output,
            markdown_output=markdown_output,
            checksum_output=checksum_output,
            source_names=args.sources,
            block_size_mb=args.block_size_mb,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
