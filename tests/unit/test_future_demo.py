"""Tests for the user-facing future-event invariance demo."""

from pit_feature_store.future_demo import run_future_event_demo


def test_future_event_demo_keeps_past_features_unchanged() -> None:
    result = run_future_event_demo()

    assert result["status"] == "pass"
    assert result["past_features_unchanged"] is True
    assert result["feature_count"] == 10
    assert result["features_before"] == result["features_after"]
