"""Train comparable raw and raw-plus-PIT CatBoost fraud baselines."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import yaml
from catboost import CatBoostClassifier, Pool
from pydantic import BaseModel, ConfigDict, Field, model_validator

from pit_feature_store.feature_registry import load_feature_registry, validate_registry_pair
from pit_feature_store.training_dataset import load_training_dataset_config

DEFAULT_CONFIG = Path("configs/model_training.yaml")
SPLITS_USED = ("train", "validation")


class ModelTrainingError(ValueError):
    """Raised when comparable model training cannot be completed safely."""


class ModelVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    include_raw_features: bool
    include_pit_features: bool
    include_pit_missing_indicators: bool

    @model_validator(mode="after")
    def validate_variant(self) -> ModelVariant:
        if not self.include_raw_features:
            raise ValueError("v1 model variants must include raw features")
        if self.include_pit_missing_indicators and not self.include_pit_features:
            raise ValueError("PIT missing indicators require PIT features")
        return self


class CatBoostConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    iterations: int = Field(ge=1)
    learning_rate: float = Field(gt=0, le=1)
    depth: int = Field(ge=1, le=16)
    l2_leaf_reg: float = Field(ge=0)
    loss_function: str
    eval_metric: str
    auto_class_weights: str
    early_stopping_rounds: int = Field(ge=1)
    thread_count: int
    verbose: int = Field(ge=0)


class ModelTrainingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    training_dataset_glob: Path
    training_dataset_version: int = Field(ge=1)
    training_dataset_config: Path
    preprocessing_artifact: Path
    primary_feature_registry: Path
    secondary_feature_registry: Path
    output_root: Path
    random_seed: int = Field(ge=0)
    variants: list[ModelVariant] = Field(min_length=2)
    catboost: CatBoostConfig

    @model_validator(mode="after")
    def validate_contract(self) -> ModelTrainingConfig:
        names = [variant.name for variant in self.variants]
        if len(names) != len(set(names)):
            raise ValueError("model variant names must be unique")
        signatures = {
            (
                variant.include_raw_features,
                variant.include_pit_features,
                variant.include_pit_missing_indicators,
            )
            for variant in self.variants
        }
        required = {(True, False, False), (True, True, True)}
        if not required.issubset(signatures):
            raise ValueError("config must contain raw-only and raw-plus-PIT variants")
        return self


def load_model_training_config(path: Path) -> ModelTrainingConfig:
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(content, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return ModelTrainingConfig.model_validate(content)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def resolve_feature_groups(config: ModelTrainingConfig) -> dict[str, list[str]]:
    dataset_config = load_training_dataset_config(config.training_dataset_config)
    expected_contracts = {
        "preprocessing_artifact": (
            dataset_config.preprocessing_artifact,
            config.preprocessing_artifact,
        ),
        "primary_feature_registry": (
            dataset_config.primary_feature_registry,
            config.primary_feature_registry,
        ),
        "secondary_feature_registry": (
            dataset_config.secondary_feature_registry,
            config.secondary_feature_registry,
        ),
    }
    mismatches = [
        name
        for name, (dataset_value, model_value) in expected_contracts.items()
        if dataset_value != model_value
    ]
    if mismatches:
        raise ModelTrainingError(f"model/training-dataset contract mismatch: {mismatches}")
    preprocessing = json.loads(config.preprocessing_artifact.read_text(encoding="utf-8"))
    raw = list(preprocessing["numeric_features"]) + list(preprocessing["categorical_features"])
    categorical = list(preprocessing["categorical_features"])

    primary = load_feature_registry(config.primary_feature_registry)
    secondary = load_feature_registry(config.secondary_feature_registry)
    validate_registry_pair(primary, secondary)
    pit = [
        f"{registry.feature_set.output_prefix}{feature.name}"
        for registry in (primary, secondary)
        for feature in registry.features
    ]
    return {
        "raw": raw,
        "categorical": categorical,
        "pit": pit,
        "pit_missing": [f"{name}__missing" for name in pit],
    }


def feature_columns_for_variant(variant: ModelVariant, groups: dict[str, list[str]]) -> list[str]:
    columns = list(groups["raw"])
    if variant.include_pit_features:
        columns.extend(groups["pit"])
    if variant.include_pit_missing_indicators:
        columns.extend(groups["pit_missing"])
    return columns


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _load_split(
    db: duckdb.DuckDBPyConnection,
    source: Path,
    split: str,
    all_features: list[str],
    categorical: set[str],
) -> tuple[Any, Any]:
    expressions = []
    for column in all_features:
        quoted = _quote_identifier(column)
        target_type = "VARCHAR" if column in categorical else "DOUBLE"
        expressions.append(f"CAST({quoted} AS {target_type}) AS {quoted}")
    query = f"""
        SELECT {", ".join(expressions)}, CAST(isFraud AS INTEGER) AS isFraud
        FROM read_parquet(?, hive_partitioning=true)
        WHERE model_split = ?
        ORDER BY TransactionDT, TransactionID
    """
    frame = db.execute(query, [str(source), split]).fetch_arrow_table().to_pandas()
    if frame.empty:
        raise ModelTrainingError(f"model split is empty: {split}")
    labels = frame.pop("isFraud")
    if labels.nunique() != 2:
        raise ModelTrainingError(f"model split must contain both labels: {split}")
    return frame, labels


def _write_importance(path: Path, columns: list[str], values: list[float]) -> None:
    ranked = sorted(zip(columns, values, strict=True), key=lambda item: item[1], reverse=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["feature", "importance"])
        writer.writerows(ranked)


def train_baseline_models(config_path: Path = DEFAULT_CONFIG) -> dict[str, object]:
    config = load_model_training_config(config_path)
    output = config.output_root / f"v{config.version}"
    if output.exists():
        raise ModelTrainingError(f"immutable model version already exists: {output}")

    groups = resolve_feature_groups(config)
    all_features = groups["raw"] + groups["pit"] + groups["pit_missing"]
    categorical = set(groups["categorical"])
    run_id = f"models_{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
    staging = config.output_root / f".{run_id}.staging"
    started_at = datetime.now(UTC)
    print(f"[model-training] run_id={run_id}", flush=True)
    print("[1/4] validating contracts and loading train/validation only", flush=True)

    db = duckdb.connect()
    try:
        schema = {
            row[0]
            for row in db.execute(
                "DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning=true)",
                [str(config.training_dataset_glob)],
            ).fetchall()
        }
        required = set(all_features) | {
            "TransactionID",
            "TransactionDT",
            "isFraud",
            "model_split",
            "training_dataset_version",
        }
        missing = sorted(required - schema)
        if missing:
            raise ModelTrainingError(f"training dataset is missing columns: {missing}")
        versions = db.execute(
            "SELECT DISTINCT training_dataset_version FROM read_parquet(?, hive_partitioning=true)",
            [str(config.training_dataset_glob)],
        ).fetchall()
        if versions != [(config.training_dataset_version,)]:
            raise ModelTrainingError(f"unexpected training dataset versions: {versions}")

        train_x, train_y = _load_split(
            db, config.training_dataset_glob, "train", all_features, categorical
        )
        validation_x, validation_y = _load_split(
            db, config.training_dataset_glob, "validation", all_features, categorical
        )
    finally:
        db.close()

    print(
        f"    train={len(train_x):,} validation={len(validation_x):,} "
        "internal_test=not_loaded",
        flush=True,
    )
    staging.mkdir(parents=True)
    results: dict[str, object] = {}
    try:
        for index, variant in enumerate(config.variants, start=1):
            columns = feature_columns_for_variant(variant, groups)
            cat_indices = [i for i, column in enumerate(columns) if column in categorical]
            print(
                f"[2/4] training {variant.name} ({index}/{len(config.variants)}): "
                f"features={len(columns)}",
                flush=True,
            )
            train_pool = Pool(train_x[columns], label=train_y, cat_features=cat_indices)
            validation_pool = Pool(
                validation_x[columns], label=validation_y, cat_features=cat_indices
            )
            parameters = config.catboost.model_dump()
            early_stopping = parameters.pop("early_stopping_rounds")
            model = CatBoostClassifier(
                **parameters,
                random_seed=config.random_seed,
                allow_writing_files=False,
            )
            model.fit(
                train_pool,
                eval_set=validation_pool,
                early_stopping_rounds=early_stopping,
                use_best_model=True,
            )
            model_path = staging / f"{variant.name}.cbm"
            model.save_model(model_path)
            importance_path = staging / f"{variant.name}_feature_importance.csv"
            _write_importance(
                importance_path, columns, model.get_feature_importance(train_pool).tolist()
            )
            best_score = model.get_best_score()
            results[variant.name] = {
                "feature_count": len(columns),
                "categorical_feature_count": len(cat_indices),
                "feature_names": columns,
                "best_iteration": int(model.get_best_iteration()),
                "best_scores": best_score,
                "model_file": model_path.name,
                "model_sha256": _sha256(model_path),
                "feature_importance_file": importance_path.name,
            }
            print(
                f"    best_iteration={model.get_best_iteration()} "
                f"validation_auc={best_score['validation']['AUC']:.6f}",
                flush=True,
            )

        print("[3/4] writing reproducibility manifest", flush=True)
        completed_at = datetime.now(UTC)
        config_content = config.model_dump(mode="json")
        manifest: dict[str, object] = {
            "run_id": run_id,
            "status": "success",
            "name": config.name,
            "model_bundle_version": config.version,
            "started_at_utc": started_at.isoformat(),
            "completed_at_utc": completed_at.isoformat(),
            "duration_seconds": round((completed_at - started_at).total_seconds(), 3),
            "random_seed": config.random_seed,
            "data_usage": {
                "train_rows": len(train_x),
                "validation_rows": len(validation_x),
                "internal_test_used": False,
                "training_dataset_version": config.training_dataset_version,
            },
            "contracts": {
                "config_sha256": _json_sha256(config_content),
                "preprocessing_artifact_sha256": _sha256(config.preprocessing_artifact),
                "primary_registry_sha256": _sha256(config.primary_feature_registry),
                "secondary_registry_sha256": _sha256(config.secondary_feature_registry),
            },
            "catboost_parameters": config.catboost.model_dump(),
            "variants": results,
        }
        manifest_path = staging / "model_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print("[4/4] publishing immutable model bundle", flush=True)
        config.output_root.mkdir(parents=True, exist_ok=True)
        staging.rename(output)
        print(f"[model-training] success: {output}", flush=True)
        return manifest
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train comparable raw and raw-plus-PIT models")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    train_baseline_models(args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
