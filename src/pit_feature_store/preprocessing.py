"""Fit leakage-safe preprocessing statistics on the temporal training period only."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from pit_feature_store.temporal_split import load_temporal_split_config

DEFAULT_CONFIG = Path("configs/preprocessing.yaml")
DEFAULT_SPLIT_CONFIG = Path("configs/training_split.yaml")
DEFAULT_SOURCE_GLOB = Path("data/silver/transactions/dataset_split=train/**/*.parquet")
DEFAULT_ARTIFACT = Path("artifacts/preprocessing/v1/preprocessor.json")
DEFAULT_REPORT = Path("reports/generated/preprocessing_fit_report.json")
RESERVED_TOKENS = {"__MISSING__", "__UNKNOWN__"}


class PreprocessingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    fit_split: str
    fit_time_column: str
    numeric_imputation: str
    categorical_encoding: str
    categorical_min_frequency: int = Field(ge=1)
    missing_category_token: str
    unknown_category_token: str
    numeric_features: list[str] = Field(min_length=1)
    categorical_features: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_contract(self) -> PreprocessingConfig:
        expected = {
            "fit_split": "train",
            "fit_time_column": "TransactionDT",
            "numeric_imputation": "median",
            "categorical_encoding": "fixed_vocabulary",
        }
        for field, value in expected.items():
            if getattr(self, field) != value:
                raise ValueError(f"{field} must equal {value!r}")
        if self.missing_category_token == self.unknown_category_token:
            raise ValueError("missing and unknown category tokens must differ")
        if set(self.numeric_features) & set(self.categorical_features):
            raise ValueError("numeric and categorical feature lists must not overlap")
        all_features = self.numeric_features + self.categorical_features
        if len(all_features) != len(set(all_features)):
            raise ValueError("preprocessing feature names must be unique")
        return self


def load_preprocessing_config(path: Path) -> PreprocessingConfig:
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(content, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return PreprocessingConfig.model_validate(content)


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _canonical_sha256(content: dict[str, object]) -> str:
    payload = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fit_preprocessor(
    source_glob: Path,
    preprocessing_config: PreprocessingConfig,
    split_config_path: Path,
    artifact_path: Path,
    report_path: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    split_config = load_temporal_split_config(split_config_path)
    train_end = split_config.boundaries.validation_start_transaction_dt
    source = str(source_glob).replace("'", "''")
    connection = duckdb.connect()
    try:
        columns = {
            row[0]
            for row in connection.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{source}', hive_partitioning=true)"
            ).fetchall()
        }
        required = {
            "TransactionID",
            "TransactionDT",
            *preprocessing_config.numeric_features,
            *preprocessing_config.categorical_features,
        }
        missing = sorted(required - columns)
        if missing:
            raise ValueError(f"preprocessing source missing columns: {missing}")

        fit_rows, fit_unique_ids, fit_min_dt, fit_max_dt = connection.execute(
            f"""
            SELECT COUNT(*)::BIGINT, COUNT(DISTINCT TransactionID)::BIGINT,
                   MIN(TransactionDT)::BIGINT, MAX(TransactionDT)::BIGINT
            FROM read_parquet('{source}', hive_partitioning=true)
            WHERE TransactionDT < {train_end}
            """
        ).fetchone()
        if fit_rows == 0 or fit_rows != fit_unique_ids or fit_max_dt >= train_end:
            raise ValueError("preprocessing fit period violates train-only contract")

        numeric_statistics: dict[str, dict[str, object]] = {}
        for feature in preprocessing_config.numeric_features:
            identifier = _quote_identifier(feature)
            median, null_count = connection.execute(
                f"""
                SELECT MEDIAN({identifier})::DOUBLE,
                       COUNT(*) FILTER (WHERE {identifier} IS NULL)::BIGINT
                FROM read_parquet('{source}', hive_partitioning=true)
                WHERE TransactionDT < {train_end}
                """
            ).fetchone()
            if median is None:
                raise ValueError(f"numeric feature has no non-null train values: {feature}")
            numeric_statistics[feature] = {
                "strategy": "median",
                "fill_value": float(median),
                "train_null_count": int(null_count),
            }

        categorical_statistics: dict[str, dict[str, object]] = {}
        for feature in preprocessing_config.categorical_features:
            identifier = _quote_identifier(feature)
            rows = connection.execute(
                f"""
                SELECT {identifier}::VARCHAR AS category, COUNT(*)::BIGINT AS frequency
                FROM read_parquet('{source}', hive_partitioning=true)
                WHERE TransactionDT < {train_end} AND {identifier} IS NOT NULL
                GROUP BY category
                HAVING COUNT(*) >= {preprocessing_config.categorical_min_frequency}
                ORDER BY category
                """
            ).fetchall()
            categories = [row[0] for row in rows]
            if RESERVED_TOKENS & set(categories):
                raise ValueError(f"source category collides with reserved token: {feature}")
            categorical_statistics[feature] = {
                "min_frequency": preprocessing_config.categorical_min_frequency,
                "categories": [
                    preprocessing_config.missing_category_token,
                    preprocessing_config.unknown_category_token,
                    *categories,
                ],
                "retained_category_count": len(categories),
            }

        artifact: dict[str, object] = {
            "artifact_type": "preprocessing_contract",
            "name": preprocessing_config.name,
            "version": preprocessing_config.version,
            "fitted_at_utc": datetime.now(UTC).isoformat(),
            "fit_policy": {
                "model_split": "train",
                "transaction_dt_start_inclusive": int(fit_min_dt),
                "transaction_dt_end_exclusive": train_end,
                "observed_max_transaction_dt": int(fit_max_dt),
                "fit_row_count": int(fit_rows),
            },
            "numeric_features": numeric_statistics,
            "categorical_features": categorical_statistics,
            "missing_category_token": preprocessing_config.missing_category_token,
            "unknown_category_token": preprocessing_config.unknown_category_token,
        }
        stable_content = dict(artifact)
        stable_content.pop("fitted_at_utc")
        artifact["semantic_sha256"] = _canonical_sha256(stable_content)

        split_metrics: dict[str, dict[str, object]] = {}
        split_case = split_config.sql_case()
        for split_name in ("train", "validation", "internal_test"):
            row_count = connection.execute(
                f"""
                SELECT COUNT(*)::BIGINT
                FROM read_parquet('{source}', hive_partitioning=true)
                WHERE ({split_case}) = ?
                """,
                [split_name],
            ).fetchone()[0]
            unknown_counts: dict[str, int] = {}
            for feature in preprocessing_config.categorical_features:
                identifier = _quote_identifier(feature)
                retained = categorical_statistics[feature]["categories"][2:]
                if retained:
                    placeholders = ", ".join("?" for _ in retained)
                    unknown = connection.execute(
                        f"""
                        SELECT COUNT(*)::BIGINT
                        FROM read_parquet('{source}', hive_partitioning=true)
                        WHERE ({split_case}) = ? AND {identifier} IS NOT NULL
                          AND {identifier} NOT IN ({placeholders})
                        """,
                        [split_name, *retained],
                    ).fetchone()[0]
                else:
                    unknown = connection.execute(
                        f"""
                        SELECT COUNT(*)::BIGINT
                        FROM read_parquet('{source}', hive_partitioning=true)
                        WHERE ({split_case}) = ? AND {identifier} IS NOT NULL
                        """,
                        [split_name],
                    ).fetchone()[0]
                unknown_counts[feature] = int(unknown)
            split_metrics[split_name] = {
                "row_count": int(row_count),
                "unknown_non_null_category_counts": unknown_counts,
            }
    finally:
        connection.close()

    report: dict[str, object] = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "preprocessing_name": preprocessing_config.name,
        "preprocessing_version": preprocessing_config.version,
        "artifact_semantic_sha256": artifact["semantic_sha256"],
        "fit_row_count": artifact["fit_policy"]["fit_row_count"],
        "fit_transaction_dt_end_exclusive": train_end,
        "validation_or_test_rows_used_for_fit": 0,
        "splits": split_metrics,
    }
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return artifact, report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fit preprocessing on temporal train only")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--split-config", type=Path, default=DEFAULT_SPLIT_CONFIG)
    parser.add_argument("--source-glob", type=Path, default=DEFAULT_SOURCE_GLOB)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_preprocessing_config(args.config)
    print(f"[preprocessing] config={config.name} v{config.version}")
    artifact, report = fit_preprocessor(
        args.source_glob, config, args.split_config, args.artifact, args.report
    )
    print(
        f"[fit] rows={report['fit_row_count']}, "
        f"TransactionDT < {report['fit_transaction_dt_end_exclusive']}"
    )
    print(f"[preprocessing] semantic_sha256={artifact['semantic_sha256']}")
    print(f"[preprocessing] success: artifact={args.artifact}, report={args.report}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
