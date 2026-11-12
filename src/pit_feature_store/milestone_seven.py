"""Complete Mốc 7 with subgroup comparison and a reproducibility manifest."""

from __future__ import annotations

import argparse
import glob
import hashlib
import importlib.metadata
import json
import platform
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from pit_feature_store.model_evaluation import (
    calculate_metrics,
    load_model_evaluation_config,
)

DEFAULT_CONFIG = Path("configs/milestone_seven.yaml")


class MilestoneSevenError(ValueError):
    """Raised when Mốc 7 outputs cannot be reconciled."""


class MilestoneSevenConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    evaluation_config: Path
    evaluation_report: Path
    prediction_glob: str
    training_dataset_manifest_glob: str
    model_manifest: Path
    preprocessing_artifact: Path
    tracked_contracts: list[Path] = Field(min_length=1)
    tracked_implementations: list[Path] = Field(min_length=1)
    output_root: Path

    @model_validator(mode="after")
    def validate_unique_paths(self) -> MilestoneSevenConfig:
        paths = self.tracked_contracts + self.tracked_implementations
        if len(paths) != len(set(paths)):
            raise ValueError("tracked reproducibility paths must be unique")
        return self


def load_milestone_seven_config(path: Path) -> MilestoneSevenConfig:
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(content, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return MilestoneSevenConfig.model_validate(content)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, object]:
    content = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(content, dict):
        raise MilestoneSevenError(f"Expected JSON object: {path}")
    return content


def _single_match(pattern: str) -> Path:
    matches = [Path(value) for value in glob.glob(pattern)]
    if len(matches) != 1:
        raise MilestoneSevenError(f"Expected exactly one file for {pattern}, found {len(matches)}")
    return matches[0]


def _metric_delta(raw: dict[str, object], pit: dict[str, object]) -> dict[str, object]:
    recall_delta = {
        target: pit["recall_at_fpr"][target]["recall"]
        - raw["recall_at_fpr"][target]["recall"]
        for target in raw["recall_at_fpr"]
    }
    precision_delta = {
        target: pit["precision_at_k"][target]["precision"]
        - raw["precision_at_k"][target]["precision"]
        for target in raw["precision_at_k"]
    }
    return {
        "roc_auc": pit["roc_auc"] - raw["roc_auc"],
        "pr_auc_average_precision": pit["pr_auc_average_precision"]
        - raw["pr_auc_average_precision"],
        "recall_at_fpr": recall_delta,
        "precision_at_k": precision_delta,
    }


def _build_comparison(
    config: MilestoneSevenConfig, evaluation_report: dict[str, object]
) -> dict[str, object]:
    evaluation_config = load_model_evaluation_config(config.evaluation_config)
    result: dict[str, object] = {"overall": {}, "by_entity_resolution_level": {}}
    for split, models in evaluation_report["results"].items():
        raw = models["raw_baseline"]
        pit = models["raw_plus_pit_mvp"]
        result["overall"][split] = {
            "raw_baseline": raw,
            "raw_plus_pit_mvp": pit,
            "pit_minus_raw": _metric_delta(raw, pit),
        }

    prediction_paths = sorted(Path(value) for value in glob.glob(config.prediction_glob))
    expected_splits = set(evaluation_config.evaluated_splits)
    if {path.stem for path in prediction_paths} != expected_splits:
        raise MilestoneSevenError("prediction files do not match evaluated splits")
    db = duckdb.connect()
    try:
        for path in prediction_paths:
            split = path.stem
            frame = db.execute(
                "SELECT * FROM read_parquet(?) ORDER BY TransactionDT, TransactionID",
                [str(path)],
            ).fetch_arrow_table().to_pandas()
            groups: dict[str, object] = {}
            for group_name, group in frame.groupby("entity_resolution_level_group", sort=True):
                labels = group["isFraud"].to_numpy()
                raw = calculate_metrics(
                    labels,
                    group["raw_baseline_fraud_probability"].to_numpy(),
                    evaluation_config.recall_at_fpr,
                    evaluation_config.precision_at_k,
                    evaluation_config.precision_at_fraction,
                )
                pit = calculate_metrics(
                    labels,
                    group["raw_plus_pit_mvp_fraud_probability"].to_numpy(),
                    evaluation_config.recall_at_fpr,
                    evaluation_config.precision_at_k,
                    evaluation_config.precision_at_fraction,
                )
                groups[str(group_name)] = {
                    "raw_baseline": raw,
                    "raw_plus_pit_mvp": pit,
                    "pit_minus_raw": _metric_delta(raw, pit),
                }
            result["by_entity_resolution_level"][split] = groups
    finally:
        db.close()
    return result


def _build_reproducibility_manifest(
    config: MilestoneSevenConfig,
    comparison_path: Path,
) -> dict[str, object]:
    training_manifest_path = _single_match(config.training_dataset_manifest_glob)
    training_manifest = _read_json(training_manifest_path)
    model_manifest = _read_json(config.model_manifest)
    evaluation_report = _read_json(config.evaluation_report)
    prediction_paths = sorted(Path(value) for value in glob.glob(config.prediction_glob))

    tracked = config.tracked_contracts + config.tracked_implementations
    missing = [str(path) for path in tracked if not path.is_file()]
    if missing:
        raise MilestoneSevenError(f"tracked reproducibility files are missing: {missing}")

    model_files: dict[str, object] = {}
    for name, details in model_manifest["variants"].items():
        path = config.model_manifest.parent / details["model_file"]
        checksum = _sha256(path)
        if checksum != details["model_sha256"]:
            raise MilestoneSevenError(f"model checksum changed: {name}")
        model_files[name] = {"path": str(path), "sha256": checksum}

    return {
        "manifest_version": config.version,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "packages": {
                name: importlib.metadata.version(name)
                for name in ["catboost", "duckdb", "numpy", "pandas", "pyarrow", "scikit-learn"]
            },
        },
        "contracts_and_code": {
            str(path): _sha256(path)
            for path in tracked
        },
        "preprocessing": {
            "path": str(config.preprocessing_artifact),
            "sha256": _sha256(config.preprocessing_artifact),
        },
        "training_dataset": {
            "manifest_path": str(training_manifest_path),
            "manifest_sha256": _sha256(training_manifest_path),
            "version": training_manifest["training_dataset_version"],
            "dataset_sha256": training_manifest["quality"]["dataset_sha256"],
            "semantic_fingerprint": training_manifest["quality"]["semantic_fingerprint"],
        },
        "models": {
            "manifest_path": str(config.model_manifest),
            "manifest_sha256": _sha256(config.model_manifest),
            "training_run_id": model_manifest["run_id"],
            "files": model_files,
        },
        "evaluation": {
            "report_path": str(config.evaluation_report),
            "report_sha256": _sha256(config.evaluation_report),
            "evaluation_run_id": evaluation_report["run_id"],
            "prediction_files": {
                str(path): _sha256(path) for path in prediction_paths
            },
            "comparison_path": str(
                config.output_root / f"v{config.version}" / comparison_path.name
            ),
            "comparison_sha256": _sha256(comparison_path),
        },
    }


def complete_milestone_seven(config_path: Path = DEFAULT_CONFIG) -> dict[str, object]:
    config = load_milestone_seven_config(config_path)
    output = config.output_root / f"v{config.version}"
    if output.exists():
        raise MilestoneSevenError(f"immutable Mốc 7 release already exists: {output}")
    run_id = f"milestone7_{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
    staging = config.output_root / f".{run_id}.staging"
    print(f"[milestone-7] run_id={run_id}", flush=True)
    print("[1/3] comparing overall and entity-resolution metrics", flush=True)
    evaluation_report = _read_json(config.evaluation_report)
    comparison = _build_comparison(config, evaluation_report)
    staging.mkdir(parents=True)
    try:
        comparison_path = staging / "model_comparison.json"
        comparison_path.write_text(
            json.dumps(comparison, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print("[2/3] hashing dataset, contracts, code, models and evaluation outputs", flush=True)
        reproducibility = _build_reproducibility_manifest(config, comparison_path)
        release = {
            "run_id": run_id,
            "status": "success",
            "name": config.name,
            "version": config.version,
            "comparison": comparison,
            "reproducibility": reproducibility,
        }
        (staging / "reproducibility_manifest.json").write_text(
            json.dumps(reproducibility, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print("[3/3] publishing immutable Mốc 7 release", flush=True)
        config.output_root.mkdir(parents=True, exist_ok=True)
        staging.rename(output)
        print(f"[milestone-7] success: {output}", flush=True)
        return release
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Complete Mốc 7 model comparison and lineage")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    complete_milestone_seven(args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
