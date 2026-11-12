"""Evaluate trained fraud baselines on validation and held-out internal test data."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import yaml
from catboost import CatBoostClassifier, Pool
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sklearn.metrics import average_precision_score, roc_auc_score, roc_curve

from pit_feature_store.model_training import (
    ModelTrainingConfig,
    load_model_training_config,
    resolve_feature_groups,
)

DEFAULT_CONFIG = Path("configs/model_evaluation.yaml")
ALLOWED_SPLITS = {"validation", "internal_test"}


class ModelEvaluationError(ValueError):
    """Raised when model evaluation cannot be completed safely."""


class ModelEvaluationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    model_training_config: Path
    model_bundle_dir: Path
    training_dataset_glob: Path
    evaluated_splits: list[str] = Field(min_length=1)
    recall_at_fpr: list[float] = Field(min_length=1)
    precision_at_k: list[int] = Field(min_length=1)
    precision_at_fraction: list[float] = Field(min_length=1)
    output_root: Path
    write_predictions: bool

    @model_validator(mode="after")
    def validate_contract(self) -> ModelEvaluationConfig:
        if len(self.evaluated_splits) != len(set(self.evaluated_splits)):
            raise ValueError("evaluated_splits must be unique")
        if not set(self.evaluated_splits).issubset(ALLOWED_SPLITS):
            raise ValueError("only validation and internal_test may be evaluated")
        if any(not 0 < value < 1 for value in self.recall_at_fpr):
            raise ValueError("recall_at_fpr values must be between 0 and 1")
        if any(value < 1 for value in self.precision_at_k):
            raise ValueError("precision_at_k values must be positive")
        if any(not 0 < value <= 1 for value in self.precision_at_fraction):
            raise ValueError("precision_at_fraction values must be in (0, 1]")
        return self


def load_model_evaluation_config(path: Path) -> ModelEvaluationConfig:
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(content, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return ModelEvaluationConfig.model_validate(content)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def calculate_recall_at_fpr(
    labels: np.ndarray, scores: np.ndarray, targets: list[float]
) -> dict[str, dict[str, float]]:
    false_positive_rates, recalls, thresholds = roc_curve(
        labels, scores, drop_intermediate=False
    )
    result: dict[str, dict[str, float]] = {}
    for target in targets:
        eligible = np.flatnonzero(false_positive_rates <= target)
        best = eligible[np.argmax(recalls[eligible])]
        result[f"{target:g}"] = {
            "target_fpr": float(target),
            "observed_fpr": float(false_positive_rates[best]),
            "recall": float(recalls[best]),
            "score_threshold": float(thresholds[best]),
        }
    return result


def calculate_precision_at_k(
    labels: np.ndarray,
    scores: np.ndarray,
    absolute_k: list[int],
    fractions: list[float],
) -> dict[str, dict[str, float | int]]:
    order = np.argsort(-scores, kind="stable")
    ranked_labels = labels[order]
    prevalence = float(labels.mean())
    requested: list[tuple[str, int]] = [(f"top_{k}", min(k, len(labels))) for k in absolute_k]
    requested.extend(
        (f"top_{fraction:g}_fraction", max(1, math.ceil(len(labels) * fraction)))
        for fraction in fractions
    )
    result: dict[str, dict[str, float | int]] = {}
    for name, k in requested:
        fraud_count = int(ranked_labels[:k].sum())
        precision = fraud_count / k
        result[name] = {
            "k": k,
            "fraction_of_rows": k / len(labels),
            "fraud_count": fraud_count,
            "precision": precision,
            "lift_over_prevalence": precision / prevalence,
        }
    return result


def calculate_metrics(
    labels: np.ndarray,
    scores: np.ndarray,
    recall_targets: list[float],
    absolute_k: list[int],
    fractions: list[float],
) -> dict[str, object]:
    if labels.ndim != 1 or scores.ndim != 1 or len(labels) != len(scores):
        raise ModelEvaluationError("labels and scores must be same-length one-dimensional arrays")
    if len(np.unique(labels)) != 2:
        raise ModelEvaluationError("evaluation labels must contain both classes")
    if not np.isfinite(scores).all():
        raise ModelEvaluationError("prediction scores contain non-finite values")
    return {
        "row_count": len(labels),
        "fraud_count": int(labels.sum()),
        "fraud_rate": float(labels.mean()),
        "roc_auc": float(roc_auc_score(labels, scores)),
        "pr_auc_average_precision": float(average_precision_score(labels, scores)),
        "recall_at_fpr": calculate_recall_at_fpr(labels, scores, recall_targets),
        "precision_at_k": calculate_precision_at_k(labels, scores, absolute_k, fractions),
    }


def _load_evaluation_split(
    db: duckdb.DuckDBPyConnection,
    source: Path,
    split: str,
    all_features: list[str],
    categorical: set[str],
) -> Any:
    metadata = ["TransactionID", "TransactionDT", "event_time", "isFraud"]
    expressions = [_quote_identifier(column) for column in metadata]
    expressions.append("CAST(entity_resolution_level AS VARCHAR) AS entity_resolution_level_group")
    for column in all_features:
        quoted = _quote_identifier(column)
        target_type = "VARCHAR" if column in categorical else "DOUBLE"
        expressions.append(f"CAST({quoted} AS {target_type}) AS {quoted}")
    query = f"""
        SELECT {', '.join(expressions)}
        FROM read_parquet(?, hive_partitioning=true)
        WHERE model_split = ?
        ORDER BY TransactionDT, TransactionID
    """
    frame = db.execute(query, [str(source), split]).fetch_arrow_table().to_pandas()
    if frame.empty or frame["isFraud"].nunique() != 2:
        raise ModelEvaluationError(f"invalid evaluation split: {split}")
    if frame["TransactionID"].nunique() != len(frame):
        raise ModelEvaluationError(f"duplicate TransactionID in evaluation split: {split}")
    return frame


def _validate_model_bundle(
    config: ModelEvaluationConfig, training_config: ModelTrainingConfig
) -> dict[str, object]:
    manifest_path = config.model_bundle_dir / "model_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["model_bundle_version"] != training_config.version:
        raise ModelEvaluationError("model bundle/training config version mismatch")
    if manifest["data_usage"]["internal_test_used"] is not False:
        raise ModelEvaluationError("internal test was already used during model training")
    expected_names = {variant.name for variant in training_config.variants}
    if set(manifest["variants"]) != expected_names:
        raise ModelEvaluationError("model variants do not match training config")
    for name, details in manifest["variants"].items():
        model_path = config.model_bundle_dir / details["model_file"]
        if _sha256(model_path) != details["model_sha256"]:
            raise ModelEvaluationError(f"model checksum mismatch: {name}")
    return manifest


def evaluate_baseline_models(config_path: Path = DEFAULT_CONFIG) -> dict[str, object]:
    config = load_model_evaluation_config(config_path)
    training_config = load_model_training_config(config.model_training_config)
    if config.training_dataset_glob != training_config.training_dataset_glob:
        raise ModelEvaluationError("evaluation source differs from model training source")
    manifest = _validate_model_bundle(config, training_config)
    groups = resolve_feature_groups(training_config)
    all_features = groups["raw"] + groups["pit"] + groups["pit_missing"]
    categorical = set(groups["categorical"])

    output = config.output_root / f"v{config.version}"
    if output.exists():
        raise ModelEvaluationError(f"immutable evaluation version already exists: {output}")
    run_id = f"evaluation_{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
    staging = config.output_root / f".{run_id}.staging"
    started_at = datetime.now(UTC)
    print(f"[model-evaluation] run_id={run_id}", flush=True)
    print("[1/4] validating model checksums and loading evaluation splits", flush=True)

    db = duckdb.connect()
    try:
        frames = {
            split: _load_evaluation_split(
                db, config.training_dataset_glob, split, all_features, categorical
            )
            for split in config.evaluated_splits
        }
    finally:
        db.close()
    print(
        "    " + " ".join(f"{split}={len(frame):,}" for split, frame in frames.items()),
        flush=True,
    )

    staging.mkdir(parents=True)
    results: dict[str, dict[str, object]] = {}
    prediction_frames: dict[str, Any] = {}
    try:
        for split, frame in frames.items():
            print(f"[2/4] scoring split={split}", flush=True)
            labels = frame["isFraud"].to_numpy(dtype=np.int8)
            prediction_frame = frame[
                [
                    "TransactionID",
                    "TransactionDT",
                    "event_time",
                    "isFraud",
                    "entity_resolution_level_group",
                ]
            ].copy()
            results[split] = {}
            for name, details in manifest["variants"].items():
                columns = details["feature_names"]
                cat_indices = [i for i, column in enumerate(columns) if column in categorical]
                model = CatBoostClassifier()
                model.load_model(config.model_bundle_dir / details["model_file"])
                pool = Pool(frame[columns], cat_features=cat_indices)
                scores = model.predict_proba(pool)[:, 1]
                prediction_frame[f"{name}_fraud_probability"] = scores
                metrics = calculate_metrics(
                    labels,
                    scores,
                    config.recall_at_fpr,
                    config.precision_at_k,
                    config.precision_at_fraction,
                )
                results[split][name] = metrics
                print(
                    f"    {name}: ROC-AUC={metrics['roc_auc']:.6f} "
                    f"PR-AUC={metrics['pr_auc_average_precision']:.6f}",
                    flush=True,
                )
            prediction_frames[split] = prediction_frame

        print("[3/4] writing metrics and auditable predictions", flush=True)
        if config.write_predictions:
            predictions_dir = staging / "predictions"
            predictions_dir.mkdir()
            for split, frame in prediction_frames.items():
                pq.write_table(
                    pa.Table.from_pandas(frame, preserve_index=False),
                    predictions_dir / f"{split}.parquet",
                    compression="zstd",
                )
        completed_at = datetime.now(UTC)
        report: dict[str, object] = {
            "run_id": run_id,
            "status": "success",
            "name": config.name,
            "evaluation_version": config.version,
            "started_at_utc": started_at.isoformat(),
            "completed_at_utc": completed_at.isoformat(),
            "duration_seconds": round((completed_at - started_at).total_seconds(), 3),
            "model_bundle_version": manifest["model_bundle_version"],
            "model_training_run_id": manifest["run_id"],
            "metric_definitions": {
                "pr_auc": "average_precision_score",
                "recall_at_fpr": "maximum recall at observed FPR <= configured target",
                "precision_at_k": "fraud share among K highest fraud probabilities",
            },
            "configured_targets": {
                "recall_at_fpr": config.recall_at_fpr,
                "precision_at_k": config.precision_at_k,
                "precision_at_fraction": config.precision_at_fraction,
            },
            "results": results,
        }
        report_path = staging / "evaluation_report.json"
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print("[4/4] publishing immutable evaluation bundle", flush=True)
        config.output_root.mkdir(parents=True, exist_ok=True)
        staging.rename(output)
        print(f"[model-evaluation] success: {output}", flush=True)
        return report
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate raw and raw-plus-PIT fraud models")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    evaluate_baseline_models(args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
