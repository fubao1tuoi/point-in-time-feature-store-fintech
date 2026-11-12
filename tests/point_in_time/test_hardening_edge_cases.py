"""Hardening tests for skew, ties, nulls, late arrivals and future invariance."""

from pathlib import Path

import duckdb

from pit_feature_store.feature_registry import load_feature_registry
from pit_feature_store.pit_features import materialize_feature_view, materialize_observations

PRIMARY = Path("configs/features/transaction_velocity_v1.yaml")


def _connection() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    connection.execute(
        """
        CREATE TABLE events (
            TransactionID BIGINT,
            event_time TIMESTAMPTZ,
            TransactionAmt DOUBLE,
            ProductCD VARCHAR,
            card_address_entity_id VARCHAR
        )
        """
    )
    return connection


def _compute(connection: duckdb.DuckDBPyConnection, output: str = "features") -> None:
    materialize_observations(connection, "events")
    materialize_feature_view(
        connection,
        "pit_observations",
        "events",
        load_feature_registry(PRIMARY),
        output_table=output,
    )


def test_skewed_entity_keeps_exact_history_count_without_duplicate_output() -> None:
    connection = _connection()
    connection.execute(
        """
        INSERT INTO events
        SELECT i,
               TIMESTAMPTZ '2017-01-01 00:00:00+00' + i * INTERVAL '1 minute',
               1.0, 'P', 'skewed_entity'
        FROM range(1, 202) source(i)
        """
    )
    _compute(connection)

    row = connection.execute(
        """
        SELECT card_addr_txn_count_7d, card_addr_amount_sum_7d
        FROM features WHERE TransactionID = 201
        """
    ).fetchone()
    rows, unique_ids = connection.execute(
        "SELECT COUNT(*), COUNT(DISTINCT TransactionID) FROM features"
    ).fetchone()

    assert row == (200, 200.0)
    assert rows == unique_ids == 201


def test_same_timestamp_uses_transaction_id_and_null_entity_stays_null() -> None:
    connection = _connection()
    connection.execute(
        """
        INSERT INTO events VALUES
          (10, TIMESTAMPTZ '2017-01-01 10:00:00+00', 10, 'P', 'entity'),
          (11, TIMESTAMPTZ '2017-01-01 10:00:00+00', 20, 'P', 'entity'),
          (12, TIMESTAMPTZ '2017-01-01 10:00:00+00', 30, 'P', 'entity'),
          (13, TIMESTAMPTZ '2017-01-01 11:00:00+00', 40, 'P', NULL)
        """
    )
    _compute(connection)

    tied = connection.execute(
        """
        SELECT TransactionID, card_addr_txn_count_1h
        FROM features WHERE TransactionID IN (10, 11, 12) ORDER BY TransactionID
        """
    ).fetchall()
    null_values = connection.execute(
        "SELECT * EXCLUDE (TransactionID) FROM features WHERE TransactionID = 13"
    ).fetchone()

    assert tied == [(10, 0), (11, 1), (12, 2)]
    assert all(value is None for value in null_values)


def test_late_event_is_included_by_event_time_but_future_event_is_excluded() -> None:
    connection = _connection()
    connection.execute(
        """
        INSERT INTO events VALUES
          (100, TIMESTAMPTZ '2017-01-01 08:00:00+00', 10, 'P', 'entity'),
          (200, TIMESTAMPTZ '2017-01-01 10:00:00+00', 20, 'P', 'entity')
        """
    )
    _compute(connection, "before_late_arrival")
    before = connection.execute(
        "SELECT card_addr_txn_count_24h FROM before_late_arrival WHERE TransactionID = 200"
    ).fetchone()[0]

    # Physically appended later, but its event time is before the observation.
    connection.execute(
        """
        INSERT INTO events VALUES
          (150, TIMESTAMPTZ '2017-01-01 09:00:00+00', 15, 'P', 'entity'),
          (300, TIMESTAMPTZ '2017-01-01 11:00:00+00', 30, 'P', 'entity')
        """
    )
    _compute(connection, "after_late_arrival")
    after = connection.execute(
        "SELECT card_addr_txn_count_24h FROM after_late_arrival WHERE TransactionID = 200"
    ).fetchone()[0]

    assert before == 1
    assert after == 2  # 08:00 + late 09:00; future 11:00 remains excluded.
