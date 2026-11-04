"""Evaluate surrogate entity-key candidates on IEEE-CIS train transactions."""

from __future__ import annotations

import argparse
import json
import math
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.csv as pacsv
import yaml

DEFAULT_SOURCE = Path("data/raw/train_transaction.csv")
DEFAULT_CONFIG = Path("configs/entities.yaml")
DEFAULT_JSON_REPORT = Path("reports/generated/entity_key_profile.json")
DEFAULT_MARKDOWN_REPORT = Path("reports/entity_key_analysis.md")
SECONDS_PER_DAY = 86_400


def quantile(values: list[float | int], probability: float) -> float | None:
    """Return an interpolated quantile without an additional dependency."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    return float(ordered[lower] * (1 - fraction) + ordered[upper] * fraction)


def safe_pct(numerator: int | float, denominator: int | float) -> float | None:
    if not denominator:
        return None
    return round(100 * numerator / denominator, 4)


@dataclass
class CandidateAccumulator:
    """Streaming state for one strict, complete-case entity candidate."""

    name: str
    columns: tuple[str, ...]
    description: str
    transaction_count: int = 0
    incomplete_transaction_count: int = 0
    entity_sizes: Counter[tuple[Any, ...]] = field(default_factory=Counter)
    first_time: dict[tuple[Any, ...], int] = field(default_factory=dict)
    last_time: dict[tuple[Any, ...], int] = field(default_factory=dict)
    fraud_counts: Counter[tuple[Any, ...]] = field(default_factory=Counter)
    non_fraud_counts: Counter[tuple[Any, ...]] = field(default_factory=Counter)

    def update(self, row: dict[str, Any]) -> None:
        self.transaction_count += 1
        values = tuple(row[column] for column in self.columns)
        if any(value is None for value in values):
            self.incomplete_transaction_count += 1
            return

        self.entity_sizes[values] += 1
        transaction_dt = int(row["TransactionDT"])
        self.first_time[values] = min(self.first_time.get(values, transaction_dt), transaction_dt)
        self.last_time[values] = max(self.last_time.get(values, transaction_dt), transaction_dt)
        if int(row["isFraud"] or 0) == 1:
            self.fraud_counts[values] += 1
        else:
            self.non_fraud_counts[values] += 1

    def summarize(self) -> dict[str, Any]:
        sizes = list(self.entity_sizes.values())
        assigned_transactions = sum(sizes)
        entity_count = len(sizes)
        singleton_entities = sum(size == 1 for size in sizes)
        repeated_entity_transactions = sum(size for size in sizes if size >= 2)
        repeated_entities = sum(size >= 2 for size in sizes)

        sorted_sizes_desc = sorted(sizes, reverse=True)
        top_10_transactions = sum(sorted_sizes_desc[:10])
        top_1pct_count = max(1, math.ceil(entity_count * 0.01)) if entity_count else 0
        top_1pct_transactions = sum(sorted_sizes_desc[:top_1pct_count])

        repeated_spans_days = [
            (self.last_time[key] - self.first_time[key]) / SECONDS_PER_DAY
            for key, size in self.entity_sizes.items()
            if size >= 2
        ]

        entities_with_fraud = sum(self.fraud_counts[key] > 0 for key in self.entity_sizes)
        mixed_label_entities = sum(
            self.fraud_counts[key] > 0 and self.non_fraud_counts[key] > 0
            for key in self.entity_sizes
        )
        fraud_transactions = sum(self.fraud_counts.values())
        fraud_in_repeated_entities = sum(
            self.fraud_counts[key] for key, size in self.entity_sizes.items() if size >= 2
        )

        return {
            "name": self.name,
            "description": self.description,
            "columns": list(self.columns),
            "total_transactions": self.transaction_count,
            "assigned_transactions": assigned_transactions,
            "assigned_transaction_pct": safe_pct(assigned_transactions, self.transaction_count),
            "incomplete_transactions": self.incomplete_transaction_count,
            "incomplete_transaction_pct": safe_pct(
                self.incomplete_transaction_count, self.transaction_count
            ),
            "unique_entities": entity_count,
            "transactions_per_entity": {
                "mean": round(assigned_transactions / entity_count, 4) if entity_count else None,
                "min": min(sizes) if sizes else None,
                "p50": quantile(sizes, 0.50),
                "p75": quantile(sizes, 0.75),
                "p90": quantile(sizes, 0.90),
                "p95": quantile(sizes, 0.95),
                "p99": quantile(sizes, 0.99),
                "max": max(sizes) if sizes else None,
            },
            "singleton_entities": singleton_entities,
            "singleton_entity_pct": safe_pct(singleton_entities, entity_count),
            "repeated_entities": repeated_entities,
            "repeat_transaction_coverage_pct_assigned": safe_pct(
                repeated_entity_transactions, assigned_transactions
            ),
            "repeat_transaction_coverage_pct_overall": safe_pct(
                repeated_entity_transactions, self.transaction_count
            ),
            "entity_skew": {
                "top_10_transaction_share_pct_assigned": safe_pct(
                    top_10_transactions, assigned_transactions
                ),
                "top_1pct_entity_count": top_1pct_count,
                "top_1pct_transaction_share_pct_assigned": safe_pct(
                    top_1pct_transactions, assigned_transactions
                ),
            },
            "repeated_entity_temporal_span_days": {
                "p50": quantile(repeated_spans_days, 0.50),
                "p90": quantile(repeated_spans_days, 0.90),
                "p95": quantile(repeated_spans_days, 0.95),
                "max": max(repeated_spans_days) if repeated_spans_days else None,
            },
            "label_diagnostics": {
                "fraud_transactions": fraud_transactions,
                "fraud_rate_pct_assigned": safe_pct(fraud_transactions, assigned_transactions),
                "entities_with_any_fraud": entities_with_fraud,
                "entities_with_any_fraud_pct": safe_pct(entities_with_fraud, entity_count),
                "mixed_label_entities": mixed_label_entities,
                "mixed_label_entity_pct": safe_pct(mixed_label_entities, entity_count),
                "fraud_in_repeated_entities_pct": safe_pct(
                    fraud_in_repeated_entities, fraud_transactions
                ),
            },
        }


def load_candidates(config_path: Path) -> list[CandidateAccumulator]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return [
        CandidateAccumulator(
            name=name,
            columns=tuple(definition["columns"]),
            description=definition["description"],
        )
        for name, definition in config["entity_candidates"].items()
    ]


def analyze_entity_candidates(
    source: Path,
    candidates: list[CandidateAccumulator],
    *,
    block_size: int = 64 * 1024 * 1024,
) -> dict[str, Any]:
    """Stream required columns and update all candidate profiles."""
    started = time.perf_counter()
    required_columns = sorted(
        {
            "TransactionID",
            "TransactionDT",
            "isFraud",
            *(column for candidate in candidates for column in candidate.columns),
        }
    )
    reader = pacsv.open_csv(
        source,
        read_options=pacsv.ReadOptions(block_size=block_size, use_threads=True),
        convert_options=pacsv.ConvertOptions(
            include_columns=required_columns,
            strings_can_be_null=True,
            null_values=["", "NA", "NaN", "nan", "null", "NULL"],
        ),
    )

    for batch in reader:
        columns = {name: batch.column(name).to_pylist() for name in required_columns}
        for index in range(batch.num_rows):
            row = {name: values[index] for name, values in columns.items()}
            for candidate in candidates:
                candidate.update(row)

    return {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source": str(source),
        "analysis_policy": {
            "null_handling": "strict_complete_case",
            "entity_definition": "exact_tuple_match",
            "label_usage": "diagnostics_only_not_part_of_key",
        },
        "candidates": [candidate.summarize() for candidate in candidates],
        "duration_seconds": round(time.perf_counter() - started, 3),
    }


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, int):
        return f"{value:,}"
    return f"{float(value):,.{digits}f}"


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Surrogate Entity Key Analysis",
        "",
        f"> Sinh tự động lúc `{report['generated_at_utc']}` từ `train_transaction.csv`.",
        "",
        "## 1. Mục tiêu",
        "",
        "IEEE-CIS không cung cấp customer/account ID. Phân tích này so sánh các tổ hợp "
        "card/address/email để chọn một surrogate entity dùng cho rolling historical features.",
        "Surrogate entity chỉ là khóa phân nhóm phục vụ nghiên cứu, không phải danh tính thật.",
        "",
        "## 2. Chính sách phân tích",
        "",
        "- **Strict complete case:** transaction thiếu bất kỳ thành phần nào của candidate "
        "sẽ không được gán entity cho candidate đó.",
        "- **Exact tuple match:** hai transaction cùng entity khi toàn bộ giá trị "
        "trong tổ hợp bằng nhau.",
        "- `isFraud` chỉ dùng chẩn đoán sau khi tạo entity, tuyệt đối không "
        "tham gia công thức key.",
        "",
        "## 3. Vì sao cần từng metric?",
        "",
        "### Assigned transaction coverage",
        "",
        "Tỷ lệ transaction có đủ tất cả thành phần để tạo key. Coverage thấp làm nhiều "
        "transaction không có historical features. Đây là chi phí trực tiếp của "
        "việc thêm cột vào key.",
        "",
        "### Unique entities",
        "",
        "Số nhóm được tạo. Quá ít entity cho thấy key quá rộng và có nguy cơ gom nhiều người/thẻ; "
        "quá nhiều entity có thể cho thấy key quá hẹp và phá vỡ lịch sử thành nhiều mảnh.",
        "",
        "### Transactions per entity: mean, median và quantiles",
        "",
        "Đo độ sâu lịch sử của entity. Median cho entity điển hình; P95/P99 cho phần đuôi; "
        "maximum giúp phát hiện nhóm bất thường. Mean đơn lẻ có thể bị entity "
        "rất lớn làm sai lệch.",
        "",
        "### Singleton entity rate",
        "",
        "Tỷ lệ entity chỉ xuất hiện một lần. Singleton không có transaction trước đó, vì vậy không "
        "tạo được velocity, recency hay rolling aggregates tại lần xuất hiện duy nhất.",
        "",
        "### Repeat transaction coverage",
        "",
        "Tỷ lệ transaction nằm trong entity có ít nhất hai giao dịch. Đây là metric trực tiếp nhất "
        "cho biết bao nhiêu transaction có khả năng hưởng lợi từ historical features. Báo cáo có "
        "cả coverage trên assigned transactions và trên toàn dataset.",
        "",
        "### Entity skew",
        "",
        "Tỷ trọng transaction thuộc top 10 và top 1% entity. Skew quá cao có thể nghĩa key gom "
        "nhiều đối tượng khác nhau, hoặc tạo hotspot làm rolling computation tốn bộ nhớ.",
        "",
        "### Temporal span của repeated entities",
        "",
        "Khoảng cách giữa transaction đầu và cuối. Entity lặp lại nhưng chỉ trong vài phút không "
        "hữu ích cho window 7/30 ngày. P50/P95 span cho biết candidate hỗ trợ "
        "được time horizon nào.",
        "",
        "### Label diagnostics",
        "",
        "Fraud rate, entity có fraud và mixed-label entity giúp hiểu candidate có gom các "
        "transaction liên quan theo labeling logic hay không. Các metric này chỉ dùng chẩn đoán; "
        "dùng label để tạo key sẽ gây target leakage.",
        "",
        "## 4. So sánh candidate keys",
        "",
        "| Candidate | Components | Assigned % | Entities | Singleton % | "
        "Repeat coverage overall % | Median tx/entity | P95 | Max |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for candidate in report["candidates"]:
        size = candidate["transactions_per_entity"]
        lines.append(
            f"| `{candidate['name']}` | `{'+'.join(candidate['columns'])}` | "
            f"{_fmt(candidate['assigned_transaction_pct'])} | "
            f"{_fmt(candidate['unique_entities'], 0)} | "
            f"{_fmt(candidate['singleton_entity_pct'])} | "
            f"{_fmt(candidate['repeat_transaction_coverage_pct_overall'])} | "
            f"{_fmt(size['p50'])} | {_fmt(size['p95'])} | {_fmt(size['max'], 0)} |"
        )

    lines.extend(
        [
            "",
            "## 5. Coverage và null trade-off",
            "",
            "| Candidate | Assigned transactions | Incomplete transactions | "
            "Incomplete % | Repeat coverage assigned % |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for candidate in report["candidates"]:
        lines.append(
            f"| `{candidate['name']}` | {_fmt(candidate['assigned_transactions'], 0)} | "
            f"{_fmt(candidate['incomplete_transactions'], 0)} | "
            f"{_fmt(candidate['incomplete_transaction_pct'])} | "
            f"{_fmt(candidate['repeat_transaction_coverage_pct_assigned'])} |"
        )

    lines.extend(
        [
            "",
            "## 6. Entity skew",
            "",
            "| Candidate | Top 10 share % | Top 1% share % | P99 tx/entity |",
            "|---|---:|---:|---:|",
        ]
    )
    for candidate in report["candidates"]:
        skew = candidate["entity_skew"]
        size = candidate["transactions_per_entity"]
        lines.append(
            f"| `{candidate['name']}` | "
            f"{_fmt(skew['top_10_transaction_share_pct_assigned'])} | "
            f"{_fmt(skew['top_1pct_transaction_share_pct_assigned'])} | "
            f"{_fmt(size['p99'])} |"
        )

    lines.extend(
        [
            "",
            "## 7. Temporal span của repeated entities",
            "",
            "| Candidate | P50 days | P90 days | P95 days | Max days |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for candidate in report["candidates"]:
        span = candidate["repeated_entity_temporal_span_days"]
        lines.append(
            f"| `{candidate['name']}` | {_fmt(span['p50'])} | {_fmt(span['p90'])} | "
            f"{_fmt(span['p95'])} | {_fmt(span['max'])} |"
        )

    lines.extend(
        [
            "",
            "## 8. Label diagnostics — không dùng để tạo key",
            "",
            "| Candidate | Fraud rate assigned % | Entities with fraud % | "
            "Mixed-label entities % | Fraud in repeated entities % |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for candidate in report["candidates"]:
        label = candidate["label_diagnostics"]
        lines.append(
            f"| `{candidate['name']}` | {_fmt(label['fraud_rate_pct_assigned'])} | "
            f"{_fmt(label['entities_with_any_fraud_pct'])} | "
            f"{_fmt(label['mixed_label_entity_pct'])} | "
            f"{_fmt(label['fraud_in_repeated_entities_pct'])} |"
        )

    lines.extend(
        [
            "",
            "## 9. Cách ra quyết định",
            "",
            "Không chọn candidate chỉ vì có nhiều entity hoặc nhiều transaction/entity nhất. "
            "Candidate phù hợp phải cân bằng:",
            "",
            "1. Coverage đủ cao để phần lớn transaction có entity.",
            "2. Repeat coverage đủ cao để rolling features có giá trị.",
            "3. Singleton rate không quá lớn.",
            "4. Top-entity concentration không bất thường.",
            "5. Temporal span phù hợp với các window 1 ngày, 7 ngày và 30 ngày.",
            "6. Thành phần key có lý do nghiệp vụ hợp lý và tương đối ổn định.",
            "",
            "Kết quả này không thể chứng minh candidate tương ứng chính xác với "
            "customer/card thật. "
            "Quyết định cuối cùng phải được ghi là một modeling assumption.",
            "",
            f"Profiling runtime: **{report['duration_seconds']:.2f} giây**.",
            "",
        ]
    )
    return "\n".join(lines)


def run_analysis(
    source: Path,
    config: Path,
    json_output: Path,
    markdown_output: Path,
) -> dict[str, Any]:
    candidates = load_candidates(config)
    report = analyze_entity_candidates(source, candidates)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_output.write_text(render_markdown(report), encoding="utf-8")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_REPORT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_REPORT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.project_root.resolve()

    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    report = run_analysis(
        source=resolve(args.source),
        config=resolve(args.config),
        json_output=resolve(args.json_output),
        markdown_output=resolve(args.markdown_output),
    )
    print(f"Analyzed {len(report['candidates'])} candidates in {report['duration_seconds']:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
