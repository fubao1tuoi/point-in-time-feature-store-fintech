"""Build a versioned, model-ready dataset from Silver and offline PIT features."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from pit_feature_store.feature_registry import (
    FeatureRegistry,
    load_feature_registry,
    validate_registry_pair,
)
from pit_feature_store.temporal_split import (
    SPLIT_NAMES,
    TemporalSplitConfig,
    load_temporal_split_config,
)

DEFAULT_CONFIG = Path("configs/training_dataset.yaml")


class TrainingDatasetError(ValueError):
    """Raised when a model-ready dataset cannot be built safely."""


class PitNullPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zero_default_aggregations: list[str]
    train_median_aggregations: list[str]
    add_missing_indicators: bool

    @model_validator(mode="after")
    def validate_aggregations(self) -> PitNullPolicy:
        zero = set(self.zero_default_aggregations)
        median = set(self.train_median_aggregations)
        if zero & median:
            raise ValueError("PIT null-policy aggregation groups must not overlap")
        expected = {"count", "sum", "count_distinct", "avg", "max", "time_since_previous"}
        if zero | median != expected:
            raise ValueError("PIT null policy must cover every supported aggregation")
        if not self.add_missing_indicators:
            raise ValueError("PIT missing indicators are required for v1")
        return self


class TrainingDatasetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    silver_source_glob: Path
    offline_feature_glob: Path
    offline_feature_table_version: int = Field(ge=1)
    temporal_split_config: Path
    preprocessing_artifact: Path
    primary_feature_registry: Path
    secondary_feature_registry: Path
    output_root: Path
    partition_column: str
    pit_null_policy: PitNullPolicy

    @model_validator(mode="after")
    def validate_contract(self) -> TrainingDatasetConfig:
        if self.partition_column != "model_split":
            raise ValueError("training dataset must partition by model_split")
        return self


def load_training_dataset_config(path: Path) -> TrainingDatasetConfig:
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(content, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return TrainingDatasetConfig.model_validate(content)


def _sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _load_json(path: Path) -> dict[str, object]:
    content = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(content, dict):
        raise TrainingDatasetError(f"Expected JSON object in {path}")
    return content


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dataset_sha256(paths: list[Path], root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(bytes.fromhex(_sha256(path)))
    return digest.hexdigest()


def _feature_map(primary: FeatureRegistry, secondary: FeatureRegistry) -> dict[str, str]:
    result: dict[str, str] = {}
    for registry in (primary, secondary):
        for feature in registry.features:
            result[f"{registry.feature_set.output_prefix}{feature.name}"] = feature.aggregation
    return result


def _categorical_expression(
    feature: str,
    statistics: dict[str, object],
    missing_token: str,
    unknown_token: str,
) -> str:
    identifier = _quote_identifier(feature)
    categories = statistics["categories"]
    retained = categories[2:]
    if retained:
        values = ", ".join(_sql_literal(value) for value in retained)
        known = f"CAST(s.{identifier} AS VARCHAR) IN ({values})"
    else:
        known = "FALSE"
    return (
        f"CASE WHEN s.{identifier} IS NULL THEN {_sql_literal(missing_token)} "
        f"WHEN {known} THEN CAST(s.{identifier} AS VARCHAR) "
        f"ELSE {_sql_literal(unknown_token)} END AS {identifier}"
    )


def _semantic_fingerprint(
    connection: duckdb.DuckDBPyConnection, table: str, columns: list[str]
) -> str:
    fields = ", ".join(
        f"{_quote_identifier(column)} := {_quote_identifier(column)}" for column in sorted(columns)
    )
    xor_hash, rows = connection.execute(
        f"""
        SELECT BIT_XOR(HASH(TO_JSON(STRUCT_PACK({fields}))))::VARCHAR,
               COUNT(*)::BIGINT
        FROM {table}
        """
    ).fetchone()
    return f"rows={rows};xor64={xor_hash}"


def _validate_preprocessing_artifact(
    artifact: dict[str, object], split_config: TemporalSplitConfig
) -> None:
    fit_policy = artifact.get("fit_policy")
    if not isinstance(fit_policy, dict):
        raise TrainingDatasetError("preprocessing artifact missing fit_policy")
    expected_end = split_config.boundaries.validation_start_transaction_dt
    if fit_policy.get("transaction_dt_end_exclusive") != expected_end:
        raise TrainingDatasetError(
            "preprocessing fit boundary does not match temporal train boundary"
        )
    if fit_policy.get("model_split") != "train":
        raise TrainingDatasetError("preprocessing artifact was not fitted on train")


def build_training_dataset(
    config: TrainingDatasetConfig,
    *,
    connection: duckdb.DuckDBPyConnection | None = None,
) -> dict[str, object]:
    """Join, transform, validate and atomically publish training dataset v1."""
    split_config = load_temporal_split_config(config.temporal_split_config)
    artifact = _load_json(config.preprocessing_artifact)
    _validate_preprocessing_artifact(artifact, split_config)
    primary = load_feature_registry(config.primary_feature_registry)
    secondary = load_feature_registry(config.secondary_feature_registry)
    validate_registry_pair(primary, secondary)
    pit_aggregations = _feature_map(primary, secondary)
    pit_columns = list(pit_aggregations)

    output_directory = config.output_root / f"v{config.version}"
    if output_directory.exists():
        raise TrainingDatasetError(f"immutable training dataset already exists: {output_directory}")
    staging = config.output_root / f".staging_{uuid.uuid4().hex}"
    owns_connection = connection is None
    db = connection or duckdb.connect()
    started_at = datetime.now(UTC)
    run_id = f"training_{started_at.strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"

    silver_source = str(config.silver_source_glob).replace("'", "''")
    offline_source = str(config.offline_feature_glob).replace("'", "''")
    try:
        print("[1/5] validating sources, versions and one-to-one join")
        db.execute(
            f"CREATE OR REPLACE TEMP VIEW silver_labeled AS "
            f"SELECT * FROM read_parquet('{silver_source}', hive_partitioning=true)"
        )
        db.execute(
            f"CREATE OR REPLACE TEMP VIEW offline_features AS "
            f"SELECT * FROM read_parquet('{offline_source}', hive_partitioning=true)"
        )
        silver_rows, silver_unique, invalid_labels = db.execute(
            """
            SELECT COUNT(*)::BIGINT, COUNT(DISTINCT TransactionID)::BIGINT,
                   COUNT(*) FILTER (WHERE isFraud NOT IN (0, 1) OR isFraud IS NULL)::BIGINT
            FROM silver_labeled
            """
        ).fetchone()
        offline_duplicates, version_mismatches = db.execute(
            f"""
            SELECT COUNT(*) - COUNT(DISTINCT TransactionID),
                   COUNT(*) FILTER (
                       WHERE feature_table_version != {config.offline_feature_table_version}
                   )
            FROM offline_features
            """
        ).fetchone()
        if (
            silver_rows != silver_unique
            or invalid_labels
            or offline_duplicates
            or version_mismatches
        ):
            raise TrainingDatasetError(
                "source quality violation: "
                f"silver={silver_rows}/{silver_unique}, invalid_labels={invalid_labels}, "
                f"offline_duplicates={offline_duplicates}, version_mismatches={version_mismatches}"
            )

        selected_raw = list(artifact["numeric_features"]) + list(artifact["categorical_features"])
        silver_columns = {row[0] for row in db.execute("DESCRIBE silver_labeled").fetchall()}
        offline_columns = {row[0] for row in db.execute("DESCRIBE offline_features").fetchall()}
        missing_silver = sorted(
            {"TransactionID", "TransactionDT", "event_time", "isFraud", *selected_raw}
            - silver_columns
        )
        missing_offline = sorted(
            {"TransactionID", "event_time", "feature_table_version", *pit_columns} - offline_columns
        )
        if missing_silver or missing_offline:
            raise TrainingDatasetError(
                f"missing source columns: silver={missing_silver}, offline={missing_offline}"
            )

        split_case = split_config.sql_case()
        raw_select = ", ".join(f"s.{_quote_identifier(name)}" for name in selected_raw)
        pit_select = ", ".join(f"f.{_quote_identifier(name)}" for name in pit_columns)
        db.execute(
            f"""
            CREATE OR REPLACE TEMP TABLE joined_training_source AS
            SELECT s.TransactionID, s.TransactionDT, s.event_time,
                   f.event_time AS feature_event_time, s.isFraud,
                   {split_case} AS model_split,
                   {raw_select}, {pit_select}, f.feature_table_version
            FROM silver_labeled AS s
            LEFT JOIN offline_features AS f USING (TransactionID)
            """
        )
        joined_rows, joined_unique, missing_features, time_mismatches = db.execute(
            """
            SELECT COUNT(*)::BIGINT, COUNT(DISTINCT TransactionID)::BIGINT,
                   COUNT(*) FILTER (WHERE feature_table_version IS NULL)::BIGINT,
                   COUNT(*) FILTER (
                       WHERE feature_event_time IS NULL
                          OR feature_event_time IS DISTINCT FROM event_time
                   )::BIGINT
            FROM joined_training_source
            """
        ).fetchone()
        if (
            joined_rows != silver_rows
            or joined_unique != silver_unique
            or missing_features
            or time_mismatches
        ):
            raise TrainingDatasetError(
                "Silver/offline join reconciliation failed: "
                f"silver={silver_rows}, joined={joined_rows}/{joined_unique}, "
                f"missing_features={missing_features}, time_mismatches={time_mismatches}"
            )

        print("[2/5] fitting nullable PIT medians on temporal train only")
        pit_fill_values: dict[str, float | int] = {}
        for column, aggregation in pit_aggregations.items():
            if aggregation in config.pit_null_policy.zero_default_aggregations:
                pit_fill_values[column] = 0
            else:
                median = db.execute(
                    f"SELECT MEDIAN({_quote_identifier(column)})::DOUBLE "
                    "FROM joined_training_source WHERE model_split = 'train'"
                ).fetchone()[0]
                if median is None:
                    raise TrainingDatasetError(f"no train values for PIT median: {column}")
                pit_fill_values[column] = float(median)

        print("[3/5] applying locked raw preprocessing and PIT null policy")
        numeric_expressions = []
        for column, statistics in artifact["numeric_features"].items():
            numeric_expressions.append(
                f"COALESCE(s.{_quote_identifier(column)}, {statistics['fill_value']}) "
                f"AS {_quote_identifier(column)}"
            )
        categorical_expressions = [
            _categorical_expression(
                column,
                statistics,
                artifact["missing_category_token"],
                artifact["unknown_category_token"],
            )
            for column, statistics in artifact["categorical_features"].items()
        ]
        pit_expressions = [
            f"COALESCE(s.{_quote_identifier(column)}, {pit_fill_values[column]}) "
            f"AS {_quote_identifier(column)}"
            for column in pit_columns
        ]
        indicator_expressions = [
            f"CAST(s.{_quote_identifier(column)} IS NULL AS TINYINT) "
            f"AS {_quote_identifier(column + '__missing')}"
            for column in pit_columns
        ]
        transformed = ", ".join(
            numeric_expressions + categorical_expressions + pit_expressions + indicator_expressions
        )
        db.execute(
            f"""
            CREATE OR REPLACE TEMP TABLE model_training_dataset AS
            SELECT s.TransactionID, s.TransactionDT, s.event_time, s.isFraud,
                   s.model_split, {transformed},
                   {config.version}::INTEGER AS training_dataset_version,
                   {artifact["version"]}::INTEGER AS preprocessing_version,
                   {split_config.version}::INTEGER AS temporal_split_version,
                   {config.offline_feature_table_version}::INTEGER
                       AS offline_feature_table_version
            FROM joined_training_source AS s
            ORDER BY s.TransactionDT, s.TransactionID
            """
        )

        model_columns = (
            selected_raw + pit_columns + [f"{column}__missing" for column in pit_columns]
        )
        null_checks = " + ".join(
            f"CAST({_quote_identifier(column)} IS NULL AS INTEGER)" for column in model_columns
        )
        output_rows, output_unique, null_model_values = db.execute(
            f"""
            SELECT COUNT(*)::BIGINT, COUNT(DISTINCT TransactionID)::BIGINT,
                   SUM({null_checks})::BIGINT
            FROM model_training_dataset
            """
        ).fetchone()
        if output_rows != silver_rows or output_unique != silver_unique or null_model_values:
            raise TrainingDatasetError(
                "transformed output quality failed: "
                f"rows={output_rows}, unique={output_unique}, null_model_values={null_model_values}"
            )

        split_rows = db.execute(
            """
            SELECT model_split, COUNT(*)::BIGINT, SUM(isFraud)::BIGINT,
                   MIN(TransactionDT)::BIGINT, MAX(TransactionDT)::BIGINT
            FROM model_training_dataset GROUP BY model_split
            """
        ).fetchall()
        split_metrics = {
            name: {
                "row_count": int(rows),
                "fraud_count": int(fraud),
                "fraud_rate": fraud / rows,
                "min_transaction_dt": int(min_dt),
                "max_transaction_dt": int(max_dt),
            }
            for name, rows, fraud, min_dt, max_dt in split_rows
        }
        if set(split_metrics) != set(SPLIT_NAMES):
            raise TrainingDatasetError("training output does not contain all model splits")

        semantic_fingerprint = _semantic_fingerprint(
            db,
            "model_training_dataset",
            ["TransactionID", "TransactionDT", "isFraud", "model_split", *model_columns],
        )

        print("[4/5] writing and reconciling partitioned Parquet")
        config.output_root.mkdir(parents=True, exist_ok=True)
        db.execute(
            f"""
            COPY model_training_dataset TO {_sql_literal(staging)}
            (FORMAT PARQUET, COMPRESSION ZSTD,
             PARTITION_BY (model_split), FILENAME_PATTERN 'part_{{i}}')
            """
        )
        staged_glob = staging / "model_split=*" / "*.parquet"
        parquet_rows, parquet_unique, parquet_nulls = db.execute(
            f"""
            SELECT COUNT(*)::BIGINT, COUNT(DISTINCT TransactionID)::BIGINT,
                   SUM({null_checks})::BIGINT
            FROM read_parquet({_sql_literal(staged_glob)}, hive_partitioning=true)
            """
        ).fetchone()
        if (parquet_rows, parquet_unique, parquet_nulls) != (
            output_rows,
            output_unique,
            0,
        ):
            raise TrainingDatasetError("staged training Parquet reconciliation failed")

        parquet_files = list(staging.rglob("*.parquet"))
        dataset_sha256 = _dataset_sha256(parquet_files, staging)
        completed_at = datetime.now(UTC)
        manifest: dict[str, object] = {
            "run_id": run_id,
            "status": "success",
            "name": config.name,
            "training_dataset_version": config.version,
            "started_at_utc": started_at.isoformat(),
            "completed_at_utc": completed_at.isoformat(),
            "duration_seconds": round((completed_at - started_at).total_seconds(), 3),
            "sources": {
                "silver_glob": str(config.silver_source_glob),
                "offline_feature_glob": str(config.offline_feature_glob),
                "offline_feature_table_version": config.offline_feature_table_version,
            },
            "contracts": {
                "temporal_split_version": split_config.version,
                "preprocessing_version": artifact["version"],
                "preprocessing_semantic_sha256": artifact["semantic_sha256"],
                "training_config_sha256": hashlib.sha256(
                    json.dumps(
                        config.model_dump(mode="json"),
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
            },
            "quality": {
                "source_rows": int(silver_rows),
                "output_rows": int(output_rows),
                "unique_transaction_ids": int(output_unique),
                "missing_offline_feature_rows": int(missing_features),
                "null_model_feature_values": int(null_model_values),
                "semantic_fingerprint": semantic_fingerprint,
                "dataset_sha256": dataset_sha256,
                "parquet_file_count": len(parquet_files),
            },
            "splits": {name: split_metrics[name] for name in SPLIT_NAMES},
            "features": {
                "raw_feature_count": len(selected_raw),
                "pit_feature_count": len(pit_columns),
                "pit_missing_indicator_count": len(pit_columns),
                "model_feature_count": len(model_columns),
                "pit_train_fill_values": pit_fill_values,
            },
        }
        manifest_dir = staging / "manifests"
        manifest_dir.mkdir()
        manifest_path = manifest_dir / f"{run_id}.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

        print("[5/5] publishing immutable training dataset version")
        staging.rename(output_directory)
        print(f"[training-dataset] success: {output_directory}")
        return manifest
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if owns_connection:
            db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build versioned model training dataset")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_training_dataset_config(args.config)
    manifest = build_training_dataset(config)
    print(
        f"[training-dataset] rows={manifest['quality']['output_rows']}, "
        f"features={manifest['features']['model_feature_count']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
