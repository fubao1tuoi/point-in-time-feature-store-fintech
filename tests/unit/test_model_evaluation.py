"""Tests for fraud ranking metrics and evaluation contracts."""

from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from pit_feature_store.model_evaluation import (
    ModelEvaluationConfig,
    calculate_metrics,
    load_model_evaluation_config,
)


def test_calculate_metrics_uses_ranked_fraud_probabilities() -> None:
    labels = np.array([0, 1, 0, 1], dtype=np.int8)
    scores = np.array([0.1, 0.9, 0.8, 0.7])

    metrics = calculate_metrics(labels, scores, [0.01, 0.5], [2], [0.5])

    assert metrics["roc_auc"] == pytest.approx(0.75)
    assert metrics["pr_auc_average_precision"] == pytest.approx(5 / 6)
    assert metrics["recall_at_fpr"]["0.01"]["recall"] == pytest.approx(0.5)
    assert metrics["recall_at_fpr"]["0.5"]["recall"] == pytest.approx(1.0)
    assert metrics["precision_at_k"]["top_2"]["precision"] == pytest.approx(0.5)
    assert metrics["precision_at_k"]["top_0.5_fraction"]["k"] == 2


def test_project_config_keeps_training_split_out_of_evaluation() -> None:
    config = load_model_evaluation_config(Path("configs/model_evaluation.yaml"))

    assert config.evaluated_splits == ["validation", "internal_test"]


def test_config_rejects_training_split() -> None:
    content = load_model_evaluation_config(Path("configs/model_evaluation.yaml")).model_dump(
        mode="json"
    )
    content["evaluated_splits"] = ["train"]

    with pytest.raises(ValidationError, match="validation and internal_test"):
        ModelEvaluationConfig.model_validate(content)
