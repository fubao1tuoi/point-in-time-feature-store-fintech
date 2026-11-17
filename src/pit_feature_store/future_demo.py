"""Executable demonstration that future events cannot change past PIT features."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

from pit_feature_store.feature_registry import load_feature_registry
from pit_feature_store.pit_features import materialize_feature_view, materialize_observations

DEFAULT_REGISTRY = Path("configs/features/transaction_velocity_v1.yaml")


def run_future_event_demo(registry_path: Path = DEFAULT_REGISTRY) -> dict[str, object]:
    """Compute a past snapshot before and after appending one future event."""
    registry = load_feature_registry(registry_path)
    connection = duckdb.connect()
    try:
        connection.execute(
            """
            CREATE TABLE demo_events (
                TransactionID BIGINT,
                event_time TIMESTAMPTZ,
                TransactionAmt DOUBLE,
                ProductCD VARCHAR,
                card_address_entity_id VARCHAR
            );
            INSERT INTO demo_events VALUES
              (100, TIMESTAMPTZ '2017-01-01 08:00:00+00', 10.0, 'W', 'entity_a'),
              (200, TIMESTAMPTZ '2017-01-01 10:00:00+00', 20.0, 'W', 'entity_a');
            """
        )
        materialize_observations(connection, "demo_events")
        materialize_feature_view(
            connection,
            "pit_observations",
            "demo_events",
            registry,
            output_table="features_before",
        )
        feature_columns = list(registry.output_columns)
        select_features = ", ".join(f'"{column}"' for column in feature_columns)
        before = connection.execute(
            f"SELECT {select_features} FROM features_before WHERE TransactionID = 200"
        ).fetchone()

        connection.execute(
            """
            INSERT INTO demo_events VALUES
              (300, TIMESTAMPTZ '2017-01-01 11:00:00+00', 999999.0, 'FUTURE', 'entity_a')
            """
        )
        materialize_observations(connection, "demo_events")
        materialize_feature_view(
            connection,
            "pit_observations",
            "demo_events",
            registry,
            output_table="features_after",
        )
        after = connection.execute(
            f"SELECT {select_features} FROM features_after WHERE TransactionID = 200"
        ).fetchone()
        assert before is not None and after is not None
        unchanged = before == after
        result = {
            "status": "pass" if unchanged else "fail",
            "observation_transaction_id": 200,
            "observation_time_utc": "2017-01-01T10:00:00Z",
            "future_transaction_id": 300,
            "future_time_utc": "2017-01-01T11:00:00Z",
            "feature_count": len(feature_columns),
            "features_before": dict(zip(feature_columns, before, strict=True)),
            "features_after": dict(zip(feature_columns, after, strict=True)),
            "past_features_unchanged": unchanged,
        }
        if not unchanged:
            raise RuntimeError("future event changed one or more past PIT features")
        return result
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--json", action="store_true", help="Print the full result as JSON")
    args = parser.parse_args()
    result = run_future_event_demo(args.registry)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        print("[future-event-demo] observation: TransactionID=200 at 10:00 UTC")
        print("[future-event-demo] appended future event: TransactionID=300 at 11:00 UTC")
        print(f"[future-event-demo] compared features: {result['feature_count']}")
        print("[future-event-demo] PASS: all past feature values remained unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
