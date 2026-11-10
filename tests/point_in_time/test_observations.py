"""Tests for the one-transaction/one-observation PIT contract."""

from pathlib import Path

import duckdb
import pytest

from pit_feature_store.pit_features import ObservationContractError, materialize_observations

GOLDEN_INPUT = Path(__file__).parent / "fixtures/golden_transactions.csv"


def _golden_connection() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    path = str(GOLDEN_INPUT).replace("'", "''")
    connection.execute(
        f"""
        CREATE TABLE golden_transactions AS
        SELECT
            CAST(TransactionID AS BIGINT) AS TransactionID,
            CAST(event_time AS TIMESTAMPTZ) AS event_time,
            TRY_CAST(NULLIF(TransactionAmt, '') AS DOUBLE) AS TransactionAmt,
            NULLIF(ProductCD, '') AS ProductCD,
            NULLIF(card_entity_id, '') AS card_entity_id,
            NULLIF(card_address_entity_id, '') AS card_address_entity_id,
            fixture_case
        FROM read_csv('{path}', all_varchar = true, header = true)
        """
    )
    return connection


def test_each_golden_transaction_becomes_one_observation() -> None:
    connection = _golden_connection()

    metrics = materialize_observations(connection, "golden_transactions")

    assert metrics.source_rows == 10
    assert metrics.observation_rows == 10
    assert metrics.null_transaction_ids == 0
    assert metrics.null_event_times == 0
    assert metrics.duplicate_transaction_ids == 0
    assert metrics.prediction_time_mismatches == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM pit_observations WHERE prediction_time = event_time"
    ).fetchone() == (10,)


def test_observation_layer_preserves_transactions_and_source_columns() -> None:
    connection = _golden_connection()
    materialize_observations(connection, "golden_transactions")

    source_ids = {
        row[0]
        for row in connection.execute(
            "SELECT TransactionID FROM golden_transactions"
        ).fetchall()
    }
    observation_ids = {
        row[0]
        for row in connection.execute("SELECT TransactionID FROM pit_observations").fetchall()
    }
    columns = {
        row[0]
        for row in connection.execute("DESCRIBE SELECT * FROM pit_observations").fetchall()
    }

    assert observation_ids == source_ids
    assert columns == {
        "TransactionID",
        "event_time",
        "TransactionAmt",
        "ProductCD",
        "card_entity_id",
        "card_address_entity_id",
        "fixture_case",
        "prediction_time",
    }


@pytest.mark.parametrize(
    ("rows_sql", "message"),
    [
        ("(NULL, TIMESTAMPTZ '2017-01-01 00:00:00+00')", "null TransactionID=1"),
        ("(1, NULL)", "null event_time=1"),
        (
            "(1, TIMESTAMPTZ '2017-01-01 00:00:00+00'), "
            "(1, TIMESTAMPTZ '2017-01-01 00:00:01+00')",
            "duplicate TransactionID rows=1",
        ),
    ],
)
def test_invalid_observation_grain_fails_fast(rows_sql: str, message: str) -> None:
    connection = duckdb.connect()
    connection.execute(
        f"""
        CREATE TABLE invalid_source(TransactionID BIGINT, event_time TIMESTAMPTZ);
        INSERT INTO invalid_source VALUES {rows_sql};
        """
    )

    with pytest.raises(ObservationContractError, match=message):
        materialize_observations(connection, "invalid_source")


def test_prediction_time_cannot_be_predefined_by_source() -> None:
    connection = duckdb.connect()
    connection.execute(
        """
        CREATE TABLE invalid_source(
            TransactionID BIGINT,
            event_time TIMESTAMPTZ,
            prediction_time TIMESTAMPTZ
        )
        """
    )

    with pytest.raises(ObservationContractError, match="must not already contain prediction_time"):
        materialize_observations(connection, "invalid_source")
