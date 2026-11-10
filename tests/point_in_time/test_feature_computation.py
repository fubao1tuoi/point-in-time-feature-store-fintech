"""End-to-end golden tests for both PIT entity feature views."""

from __future__ import annotations

import csv
from pathlib import Path

import duckdb
import pytest

from pit_feature_store.feature_registry import load_feature_registry
from pit_feature_store.pit_features import (
    materialize_feature_view,
    materialize_observations,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures"


def _connection_with_golden_source() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    fixture = (FIXTURES / "golden_transactions.csv").as_posix()
    connection.execute(
        f"""
        CREATE TABLE golden_transactions AS
        SELECT
            TransactionID::BIGINT AS TransactionID,
            event_time::TIMESTAMPTZ AS event_time,
            TransactionAmt::DOUBLE AS TransactionAmt,
            ProductCD,
            card_entity_id,
            card_address_entity_id,
            fixture_case
        FROM read_csv_auto('{fixture}', nullstr='')
        """
    )
    materialize_observations(connection, "golden_transactions")
    return connection


def _expected() -> dict[int, dict[str, str]]:
    with (FIXTURES / "golden_expected_features.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        return {int(row["TransactionID"]): row for row in csv.DictReader(handle)}


def _primary_registry():
    return load_feature_registry(ROOT / "configs/features/transaction_velocity_v1.yaml")


def _materialize_primary(
    connection: duckdb.DuckDBPyConnection, output_table: str = "primary_features"
) -> None:
    materialize_feature_view(
        connection,
        "pit_observations",
        "golden_transactions",
        _primary_registry(),
        output_table=output_table,
    )


def _table_snapshot(
    connection: duckdb.DuckDBPyConnection, table: str
) -> list[tuple[object, ...]]:
    return connection.execute(f"SELECT * FROM {table} ORDER BY TransactionID").fetchall()


@pytest.mark.parametrize(
    ("registry_path", "output_table", "prefix"),
    [
        ("transaction_velocity_v1.yaml", "primary_features", "card_addr_"),
        ("transaction_velocity_card_v1.yaml", "secondary_features", "card_"),
    ],
)
def test_feature_view_matches_all_hand_calculated_golden_values(
    registry_path: str, output_table: str, prefix: str
) -> None:
    connection = _connection_with_golden_source()
    registry = load_feature_registry(ROOT / "configs/features" / registry_path)

    metrics = materialize_feature_view(
        connection,
        "pit_observations",
        "golden_transactions",
        registry,
        output_table=output_table,
    )

    rows = connection.execute(f"SELECT * FROM {output_table}").fetchall()
    columns = [item[0] for item in connection.description]
    expected = _expected()
    assert metrics.observation_rows == metrics.output_rows == 10
    assert len(metrics.feature_columns) == 10

    for values in rows:
        actual = dict(zip(columns, values, strict=True))
        transaction_id = actual.pop("TransactionID")
        for column, value in actual.items():
            assert column.startswith(prefix)
            expected_value = expected[transaction_id][column]
            if expected_value == "null":
                assert value is None
            else:
                assert float(value) == pytest.approx(float(expected_value))


def test_both_views_can_be_joined_without_changing_observation_grain() -> None:
    connection = _connection_with_golden_source()
    primary = load_feature_registry(
        ROOT / "configs/features/transaction_velocity_v1.yaml"
    )
    secondary = load_feature_registry(
        ROOT / "configs/features/transaction_velocity_card_v1.yaml"
    )
    materialize_feature_view(
        connection,
        "pit_observations",
        "golden_transactions",
        primary,
        output_table="primary_features",
    )
    materialize_feature_view(
        connection,
        "pit_observations",
        "golden_transactions",
        secondary,
        output_table="secondary_features",
    )

    connection.execute(
        """
        CREATE TEMP TABLE combined_features AS
        SELECT * FROM primary_features
        JOIN secondary_features USING (TransactionID)
        """
    )
    row_count, unique_ids = connection.execute(
        """
        SELECT COUNT(*), COUNT(DISTINCT TransactionID)
        FROM combined_features
        """
    ).fetchone()
    assert row_count == unique_ids == 10
    assert len(connection.execute("DESCRIBE combined_features").fetchall()) == 21


def test_cutoff_excludes_current_and_future_rows_but_orders_same_timestamp() -> None:
    connection = _connection_with_golden_source()
    _materialize_primary(connection)

    rows = {
        row[0]: row[1:]
        for row in connection.execute(
            """
            SELECT TransactionID, card_addr_txn_count_7d,
                   card_addr_amount_sum_7d, card_addr_seconds_since_previous_txn
            FROM primary_features
            WHERE TransactionID IN (101, 102, 103)
            """
        ).fetchall()
    }
    assert rows[101] == (0, 0.0, None)
    assert rows[102] == (1, 10.0, 604800)
    assert rows[103] == (2, 30.0, 0)


def test_window_start_is_inclusive_for_1h_24h_and_7d() -> None:
    connection = _connection_with_golden_source()
    _materialize_primary(connection)

    boundary_rows = connection.execute(
        """
        SELECT TransactionID, card_addr_txn_count_1h,
               card_addr_txn_count_24h, card_addr_txn_count_7d
        FROM primary_features
        WHERE TransactionID IN (102, 105, 106)
        ORDER BY TransactionID
        """
    ).fetchall()
    assert boundary_rows == [
        (102, 0, 0, 1),
        (105, 3, 3, 3),
        (106, 0, 4, 4),
    ]


def test_no_history_and_null_entity_keep_observations_with_contract_defaults() -> None:
    connection = _connection_with_golden_source()
    metrics = materialize_feature_view(
        connection,
        "pit_observations",
        "golden_transactions",
        _primary_registry(),
        output_table="primary_features",
    )

    no_history = connection.execute(
        """
        SELECT card_addr_txn_count_1h, card_addr_amount_sum_1h,
               card_addr_amount_avg_24h, card_addr_seconds_since_previous_txn
        FROM primary_features WHERE TransactionID = 101
        """
    ).fetchone()
    null_entity = connection.execute(
        "SELECT * EXCLUDE (TransactionID) FROM primary_features WHERE TransactionID = 301"
    ).fetchone()
    assert metrics.null_entity_rows == 2
    assert no_history == (0, 0.0, None, None)
    assert all(value is None for value in null_entity)


def test_appending_future_history_does_not_change_past_features() -> None:
    connection = _connection_with_golden_source()
    _materialize_primary(connection, "features_before_append")
    before = _table_snapshot(connection, "features_before_append")

    connection.execute(
        """
        INSERT INTO golden_transactions VALUES
        (999, TIMESTAMPTZ '2030-01-01 00:00:00+00', 999999.0, 'FUTURE',
         'ce_card_a', 'cae_card_a_addr_1', 'future_append')
        """
    )
    _materialize_primary(connection, "features_after_append")
    after = _table_snapshot(connection, "features_after_append")

    assert after == before


def test_rerun_is_deterministic_even_when_history_physical_order_changes() -> None:
    connection = _connection_with_golden_source()
    _materialize_primary(connection, "features_first_run")
    first = _table_snapshot(connection, "features_first_run")

    connection.execute(
        """
        CREATE OR REPLACE TABLE golden_transactions AS
        SELECT * FROM golden_transactions ORDER BY TransactionID DESC
        """
    )
    _materialize_primary(connection, "features_second_run")
    second = _table_snapshot(connection, "features_second_run")

    assert second == first
