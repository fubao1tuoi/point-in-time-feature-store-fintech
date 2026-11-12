"""Tests for Mốc 7 comparison and reproducibility contracts."""

from pathlib import Path

import pytest

from pit_feature_store.milestone_seven import _metric_delta, load_milestone_seven_config


def test_metric_delta_preserves_operating_points() -> None:
    raw = {
        "roc_auc": 0.8,
        "pr_auc_average_precision": 0.2,
        "recall_at_fpr": {"0.01": {"recall": 0.1}},
        "precision_at_k": {"top_100": {"precision": 0.4}},
    }
    pit = {
        "roc_auc": 0.83,
        "pr_auc_average_precision": 0.25,
        "recall_at_fpr": {"0.01": {"recall": 0.13}},
        "precision_at_k": {"top_100": {"precision": 0.5}},
    }

    delta = _metric_delta(raw, pit)

    assert delta["roc_auc"] == pytest.approx(0.03)
    assert delta["pr_auc_average_precision"] == pytest.approx(0.05)
    assert delta["recall_at_fpr"]["0.01"] == pytest.approx(0.03)
    assert delta["precision_at_k"]["top_100"] == pytest.approx(0.1)


def test_project_config_tracks_all_milestone_contracts() -> None:
    config = load_milestone_seven_config(Path("configs/milestone_seven.yaml"))

    assert config.version == 1
    assert Path("configs/model_evaluation.yaml") in config.tracked_contracts
    assert Path("src/pit_feature_store/model_evaluation.py") in config.tracked_implementations
