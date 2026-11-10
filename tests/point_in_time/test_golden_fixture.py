"""Structural checks for the manually designed PIT golden input."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from pit_feature_store.feature_registry import load_feature_registry

FIXTURE = Path(__file__).parent / "fixtures/golden_transactions.csv"
EXPECTED = Path(__file__).parent / "fixtures/golden_expected_features.csv"


def _load_rows() -> list[dict[str, str]]:
    with FIXTURE.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _time(row: dict[str, str]) -> datetime:
    return datetime.fromisoformat(row["event_time"].replace("Z", "+00:00"))


def _load_expected_rows() -> list[dict[str, str]]:
    with EXPECTED.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_golden_fixture_has_unique_observations_and_all_named_cases() -> None:
    rows = _load_rows()
    transaction_ids = [int(row["TransactionID"]) for row in rows]

    assert len(rows) == 10
    assert len(transaction_ids) == len(set(transaction_ids))
    assert {row["fixture_case"] for row in rows} == {
        "no_history",
        "seven_day_boundary",
        "same_timestamp",
        "entity_isolation",
        "secondary_other_primary",
        "null_primary",
        "null_both_entities",
        "null_values",
        "one_hour_boundary",
        "twenty_four_hour_boundary",
    }


def test_golden_fixture_encodes_time_boundaries_and_same_timestamp() -> None:
    rows = {int(row["TransactionID"]): row for row in _load_rows()}

    assert (_time(rows[102]) - _time(rows[101])).total_seconds() == 7 * 24 * 60 * 60
    assert (_time(rows[105]) - _time(rows[102])).total_seconds() == 60 * 60
    assert (_time(rows[106]) - _time(rows[102])).total_seconds() == 24 * 60 * 60
    assert _time(rows[102]) == _time(rows[103])
    assert 102 < 103


def test_golden_fixture_encodes_entity_and_null_cases() -> None:
    rows = {int(row["TransactionID"]): row for row in _load_rows()}

    assert rows[501]["card_entity_id"] == rows[102]["card_entity_id"]
    assert rows[501]["card_address_entity_id"] != rows[102]["card_address_entity_id"]
    assert rows[301]["card_entity_id"] != ""
    assert rows[301]["card_address_entity_id"] == ""
    assert rows[401]["card_entity_id"] == ""
    assert rows[401]["card_address_entity_id"] == ""
    assert rows[104]["TransactionAmt"] == ""
    assert rows[104]["ProductCD"] == ""


def test_golden_fixture_is_not_stored_in_logical_order() -> None:
    rows = _load_rows()
    physical_order = [int(row["TransactionID"]) for row in rows]
    logical_order = [
        int(row["TransactionID"])
        for row in sorted(rows, key=lambda row: (_time(row), int(row["TransactionID"])))
    ]

    assert physical_order != logical_order


def test_expected_fixture_matches_registry_outputs_and_observations() -> None:
    project_root = Path(__file__).resolve().parents[2]
    primary = load_feature_registry(
        project_root / "configs/features/transaction_velocity_v1.yaml"
    )
    secondary = load_feature_registry(
        project_root / "configs/features/transaction_velocity_card_v1.yaml"
    )
    expected_rows = _load_expected_rows()
    expected_columns = ["TransactionID", *primary.output_columns, *secondary.output_columns]

    assert list(expected_rows[0]) == expected_columns
    assert {row["TransactionID"] for row in expected_rows} == {
        row["TransactionID"] for row in _load_rows()
    }
    assert all(value != "" for row in expected_rows for value in row.values())
    for row in expected_rows:
        for column in expected_columns[1:]:
            if row[column] != "null":
                float(row[column])


def test_expected_fixture_encodes_manual_edge_case_results() -> None:
    expected = {int(row["TransactionID"]): row for row in _load_expected_rows()}

    assert expected[101]["card_addr_amount_avg_24h"] == "null"
    assert expected[102]["card_addr_txn_count_7d"] == "1"
    assert expected[102]["card_addr_txn_count_24h"] == "0"
    assert expected[102]["card_addr_seconds_since_previous_txn"] == "604800"
    assert expected[103]["card_addr_txn_count_1h"] == "1"
    assert expected[103]["card_addr_seconds_since_previous_txn"] == "0"
    assert all(value == "null" for key, value in expected[401].items() if key != "TransactionID")
    assert expected[301]["card_addr_txn_count_1h"] == "null"
    assert expected[301]["card_txn_count_1h"] == "3"
    assert expected[105]["card_addr_txn_count_1h"] == "3"
    assert expected[106]["card_addr_txn_count_1h"] == "0"
    assert expected[106]["card_addr_txn_count_24h"] == "4"
    assert expected[106]["card_txn_count_24h"] == "6"
