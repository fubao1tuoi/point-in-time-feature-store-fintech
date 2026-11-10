"""Point-in-Time feature computation primitives."""

from __future__ import annotations

import re
from dataclasses import dataclass

import duckdb

from pit_feature_store.feature_registry import FeatureDefinition, FeatureRegistry

IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
REQUIRED_OBSERVATION_SOURCE_COLUMNS = {"TransactionID", "event_time"}


class ObservationContractError(ValueError):
    """Raised when source data cannot form one valid observation per transaction."""


class FeatureComputationError(ValueError):
    """Raised when a feature view cannot be computed safely."""


@dataclass(frozen=True)
class ObservationMetrics:
    source_table: str
    output_table: str
    source_rows: int
    observation_rows: int
    null_transaction_ids: int
    null_event_times: int
    duplicate_transaction_ids: int
    prediction_time_mismatches: int


@dataclass(frozen=True)
class FeatureViewMetrics:
    entity_key: str
    output_table: str
    observation_rows: int
    output_rows: int
    feature_columns: tuple[str, ...]
    null_entity_rows: int


def _quote_identifier(value: str) -> str:
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(f"Invalid SQL identifier: {value!r}")
    return f'"{value}"'


def _table_columns(connection: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    quoted = _quote_identifier(table)
    return [row[0] for row in connection.execute(f"DESCRIBE SELECT * FROM {quoted}").fetchall()]


def materialize_observations(
    connection: duckdb.DuckDBPyConnection,
    source_table: str,
    *,
    output_table: str = "pit_observations",
) -> ObservationMetrics:
    """Create one observation per source transaction with prediction_time=event_time."""
    source = _quote_identifier(source_table)
    output = _quote_identifier(output_table)
    if source_table == output_table:
        raise ValueError("source_table and output_table must be different")

    columns = set(_table_columns(connection, source_table))
    missing = sorted(REQUIRED_OBSERVATION_SOURCE_COLUMNS - columns)
    if missing:
        raise ObservationContractError(f"observation source missing required columns: {missing}")
    if "prediction_time" in columns:
        raise ObservationContractError(
            "observation source must not already contain prediction_time; "
            "it is derived from event_time"
        )

    quality = connection.execute(
        f"""
        SELECT
            COUNT(*)::BIGINT AS row_count,
            COUNT(*) FILTER (WHERE TransactionID IS NULL)::BIGINT AS null_transaction_ids,
            COUNT(*) FILTER (WHERE event_time IS NULL)::BIGINT AS null_event_times,
            (COUNT(TransactionID) - COUNT(DISTINCT TransactionID))::BIGINT
                AS duplicate_transaction_ids
        FROM {source}
        """
    ).fetchone()
    assert quality is not None
    source_rows, null_ids, null_times, duplicate_ids = map(int, quality)

    violations = []
    if null_ids:
        violations.append(f"null TransactionID={null_ids}")
    if null_times:
        violations.append(f"null event_time={null_times}")
    if duplicate_ids:
        violations.append(f"duplicate TransactionID rows={duplicate_ids}")
    if violations:
        raise ObservationContractError("invalid observation source: " + ", ".join(violations))

    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {output} AS
        SELECT
            source.*,
            source.event_time AS prediction_time
        FROM {source} AS source
        """
    )

    output_quality = connection.execute(
        f"""
        SELECT
            COUNT(*)::BIGINT AS observation_rows,
            COUNT(*) FILTER (
                WHERE prediction_time IS DISTINCT FROM event_time
            )::BIGINT AS prediction_time_mismatches
        FROM {output}
        """
    ).fetchone()
    assert output_quality is not None
    observation_rows, prediction_mismatches = map(int, output_quality)

    if observation_rows != source_rows:
        raise ObservationContractError(
            f"observation row count mismatch: source={source_rows}, output={observation_rows}"
        )
    if prediction_mismatches:
        raise ObservationContractError(
            f"prediction_time must equal event_time; mismatches={prediction_mismatches}"
        )

    return ObservationMetrics(
        source_table=source_table,
        output_table=output_table,
        source_rows=source_rows,
        observation_rows=observation_rows,
        null_transaction_ids=null_ids,
        null_event_times=null_times,
        duplicate_transaction_ids=duplicate_ids,
        prediction_time_mismatches=prediction_mismatches,
    )


def _window_seconds(window: str) -> int:
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return int(window[:-1]) * units[window[-1]]


def _history_predicate(entity_key: str, window: str | None) -> str:
    entity = _quote_identifier(entity_key)
    predicates = [
        f"history.{entity} = observation.{entity}",
        "(history.event_time, history.TransactionID) "
        "< (observation.prediction_time, observation.TransactionID)",
    ]
    if window is not None:
        seconds = _window_seconds(window)
        predicates.append(
            "history.event_time >= "
            f"observation.prediction_time - INTERVAL '{seconds} seconds'"
        )
    return " AND ".join(predicates)


def _aggregate_expression(feature: FeatureDefinition, predicate: str) -> str:
    value = _quote_identifier(feature.value_column) if feature.value_column else None
    if feature.aggregation == "count":
        return f"SELECT COUNT(*)::BIGINT FROM history_source AS history WHERE {predicate}"
    if feature.aggregation == "sum":
        return (
            f"SELECT COALESCE(SUM(history.{value}), 0.0) "
            f"FROM history_source AS history WHERE {predicate}"
        )
    if feature.aggregation == "avg":
        return f"SELECT AVG(history.{value}) FROM history_source AS history WHERE {predicate}"
    if feature.aggregation == "max":
        return f"SELECT MAX(history.{value}) FROM history_source AS history WHERE {predicate}"
    if feature.aggregation == "count_distinct":
        return (
            f"SELECT COUNT(DISTINCT history.{value})::BIGINT "
            f"FROM history_source AS history WHERE {predicate}"
        )
    if feature.aggregation == "time_since_previous":
        return (
            "SELECT date_diff('second', MAX(history.event_time), observation.prediction_time) "
            f"FROM history_source AS history WHERE {predicate}"
        )
    raise FeatureComputationError(f"unsupported aggregation: {feature.aggregation}")


def materialize_feature_view(
    connection: duckdb.DuckDBPyConnection,
    observations_table: str,
    history_table: str,
    registry: FeatureRegistry,
    *,
    output_table: str,
) -> FeatureViewMetrics:
    """Compute one registry-driven PIT feature view for every observation."""
    observations = _quote_identifier(observations_table)
    history = _quote_identifier(history_table)
    output = _quote_identifier(output_table)
    entity_key = registry.feature_set.entity_key

    observation_columns = set(_table_columns(connection, observations_table))
    history_columns = set(_table_columns(connection, history_table))
    required_observation = {"TransactionID", "prediction_time", entity_key}
    required_history = {"TransactionID", "event_time", entity_key}
    required_history.update(
        feature.value_column
        for feature in registry.features
        if feature.value_column is not None
    )
    missing_observation = sorted(required_observation - observation_columns)
    missing_history = sorted(required_history - history_columns)
    if missing_observation or missing_history:
        raise FeatureComputationError(
            "missing feature input columns: "
            f"observations={missing_observation}, history={missing_history}"
        )

    expressions = []
    for feature in registry.features:
        predicate = _history_predicate(entity_key, feature.window)
        aggregate = _aggregate_expression(feature, predicate)
        output_column = _quote_identifier(
            f"{registry.feature_set.output_prefix}{feature.name}"
        )
        expressions.append(
            f"CASE WHEN observation.{_quote_identifier(entity_key)} IS NULL "
            f"THEN NULL ELSE ({aggregate}) END AS {output_column}"
        )

    connection.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW history_source AS SELECT * FROM {history};
        CREATE OR REPLACE TEMP TABLE {output} AS
        SELECT
            observation.TransactionID,
            {", ".join(expressions)}
        FROM {observations} AS observation
        ORDER BY observation.TransactionID
        """
    )

    observation_rows = int(connection.execute(f"SELECT COUNT(*) FROM {observations}").fetchone()[0])
    output_rows = int(connection.execute(f"SELECT COUNT(*) FROM {output}").fetchone()[0])
    duplicate_outputs = int(
        connection.execute(
            f"SELECT COUNT(*) - COUNT(DISTINCT TransactionID) FROM {output}"
        ).fetchone()[0]
    )
    if output_rows != observation_rows or duplicate_outputs:
        raise FeatureComputationError(
            "feature output grain violation: "
            f"observations={observation_rows}, output={output_rows}, "
            f"duplicate_outputs={duplicate_outputs}"
        )

    null_entity_rows = int(
        connection.execute(
            f"SELECT COUNT(*) FROM {observations} "
            f"WHERE {_quote_identifier(entity_key)} IS NULL"
        ).fetchone()[0]
    )
    return FeatureViewMetrics(
        entity_key=entity_key,
        output_table=output_table,
        observation_rows=observation_rows,
        output_rows=output_rows,
        feature_columns=tuple(registry.output_columns),
        null_entity_rows=null_entity_rows,
    )
