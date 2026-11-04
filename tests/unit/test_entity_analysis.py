from pit_feature_store.entity_analysis import CandidateAccumulator, quantile


def test_quantile_interpolates_values() -> None:
    assert quantile([1, 2, 3, 4], 0.5) == 2.5
    assert quantile([], 0.5) is None


def test_candidate_metrics_capture_coverage_repeat_skew_and_labels() -> None:
    candidate = CandidateAccumulator(
        name="card_addr",
        columns=("card1", "addr1"),
        description="test",
    )
    rows = [
        {"card1": 1, "addr1": 10, "TransactionDT": 0, "isFraud": 0},
        {"card1": 1, "addr1": 10, "TransactionDT": 86_400, "isFraud": 1},
        {"card1": 2, "addr1": 20, "TransactionDT": 10, "isFraud": 0},
        {"card1": 3, "addr1": None, "TransactionDT": 20, "isFraud": 0},
    ]
    for row in rows:
        candidate.update(row)

    result = candidate.summarize()

    assert result["assigned_transactions"] == 3
    assert result["incomplete_transactions"] == 1
    assert result["unique_entities"] == 2
    assert result["singleton_entities"] == 1
    assert result["repeat_transaction_coverage_pct_overall"] == 50.0
    assert result["transactions_per_entity"]["max"] == 2
    assert result["repeated_entity_temporal_span_days"]["p50"] == 1.0
    assert result["label_diagnostics"]["mixed_label_entities"] == 1
