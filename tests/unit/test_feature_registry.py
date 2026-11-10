from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from pit_feature_store.feature_registry import (
    FeatureRegistry,
    load_feature_registry,
    validate_registry_pair,
)


def _registry_dict() -> dict[str, object]:
    return {
        "feature_set": {
            "name": "card_address_transaction_velocity",
            "version": 1,
            "entity_key": "card_address_entity_id",
            "source": "silver_transactions",
            "event_timestamp": "event_time",
            "observation_id": "TransactionID",
            "ordering_columns": ["event_time", "TransactionID"],
            "cutoff_policy": "lexicographic_strict_before",
            "same_timestamp_policy": "lower_transaction_id_is_earlier",
            "current_event_policy": "exclude",
            "window_start_boundary": "inclusive",
            "output_prefix": "card_addr_",
            "owner": "data-engineering",
        },
        "features": [
            {
                "name": "txn_count_1h",
                "description": "Historical transaction count",
                "aggregation": "count",
                "window": "1h",
                "no_history_value": 0,
            },
            {
                "name": "amount_sum_1h",
                "description": "Historical amount sum",
                "aggregation": "sum",
                "value_column": "TransactionAmt",
                "window": "1h",
                "ignore_null_values": True,
                "no_history_value": 0.0,
            },
            {
                "name": "seconds_since_previous_txn",
                "description": "Recency",
                "aggregation": "time_since_previous",
                "no_history_value": None,
            },
        ],
    }


def test_repository_feature_registries_are_valid_and_aligned() -> None:
    project_root = Path(__file__).resolve().parents[2]
    primary = load_feature_registry(
        project_root / "configs/features/transaction_velocity_v1.yaml"
    )
    secondary = load_feature_registry(
        project_root / "configs/features/transaction_velocity_card_v1.yaml"
    )

    validate_registry_pair(primary, secondary)

    assert len(primary.features) == 10
    assert len(secondary.features) == 10
    assert len(primary.output_columns) == 10
    assert primary.output_columns[0] == "card_addr_txn_count_1h"
    assert secondary.output_columns[0] == "card_txn_count_1h"


def test_unknown_registry_fields_are_rejected() -> None:
    data = _registry_dict()
    data["feature_set"]["unexpected"] = True  # type: ignore[index]

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        FeatureRegistry.model_validate(data)


def test_duplicate_feature_names_are_rejected() -> None:
    data = _registry_dict()
    features = data["features"]  # type: ignore[assignment]
    features.append(deepcopy(features[0]))  # type: ignore[union-attr,index]

    with pytest.raises(ValidationError, match="feature names must be unique"):
        FeatureRegistry.model_validate(data)


@pytest.mark.parametrize("window", ["0h", "1hour", "-1d", "7 d", ""])
def test_invalid_window_format_is_rejected(window: str) -> None:
    data = _registry_dict()
    data["features"][0]["window"] = window  # type: ignore[index]

    with pytest.raises(ValidationError, match="window must be a positive integer"):
        FeatureRegistry.model_validate(data)


def test_bounded_aggregation_requires_window() -> None:
    data = _registry_dict()
    del data["features"][0]["window"]  # type: ignore[index]

    with pytest.raises(ValidationError, match="aggregation 'count' requires window"):
        FeatureRegistry.model_validate(data)


def test_value_aggregation_requires_value_column_and_null_policy() -> None:
    data = _registry_dict()
    feature = data["features"][1]  # type: ignore[index]
    del feature["value_column"]

    with pytest.raises(ValidationError, match="aggregation 'sum' requires value_column"):
        FeatureRegistry.model_validate(data)

    data = _registry_dict()
    data["features"][1]["ignore_null_values"] = False  # type: ignore[index]
    with pytest.raises(ValidationError, match="requires ignore_null_values=true"):
        FeatureRegistry.model_validate(data)


def test_time_since_previous_forbids_window_and_value_column() -> None:
    data = _registry_dict()
    data["features"][2]["window"] = "7d"  # type: ignore[index]

    with pytest.raises(ValidationError, match="must not define a bounded window"):
        FeatureRegistry.model_validate(data)

    data = _registry_dict()
    data["features"][2]["value_column"] = "TransactionAmt"  # type: ignore[index]
    with pytest.raises(ValidationError, match="forbids value_column"):
        FeatureRegistry.model_validate(data)


@pytest.mark.parametrize(
    ("feature_index", "bad_default", "message"),
    [
        (0, None, "requires no_history_value=0"),
        (1, None, "requires no_history_value=0"),
        (2, 0, "requires no_history_value=null"),
    ],
)
def test_no_history_default_must_match_aggregation(
    feature_index: int, bad_default: object, message: str
) -> None:
    data = _registry_dict()
    data["features"][feature_index]["no_history_value"] = bad_default  # type: ignore[index]

    with pytest.raises(ValidationError, match=message):
        FeatureRegistry.model_validate(data)


def test_pit_order_and_entity_prefix_are_enforced() -> None:
    data = _registry_dict()
    data["feature_set"]["ordering_columns"] = [  # type: ignore[index]
        "TransactionID",
        "event_time",
    ]
    with pytest.raises(ValidationError, match="ordering_columns must equal"):
        FeatureRegistry.model_validate(data)

    data = _registry_dict()
    data["feature_set"]["output_prefix"] = "card_"  # type: ignore[index]
    with pytest.raises(ValidationError, match="requires output_prefix 'card_addr_'"):
        FeatureRegistry.model_validate(data)


def test_primary_secondary_semantic_mismatch_is_rejected() -> None:
    primary = FeatureRegistry.model_validate(_registry_dict())
    secondary_data = _registry_dict()
    feature_set = secondary_data["feature_set"]  # type: ignore[assignment]
    feature_set["name"] = "card_transaction_velocity"  # type: ignore[index]
    feature_set["entity_key"] = "card_entity_id"  # type: ignore[index]
    feature_set["output_prefix"] = "card_"  # type: ignore[index]
    secondary_data["features"][0]["window"] = "24h"  # type: ignore[index]
    secondary = FeatureRegistry.model_validate(secondary_data)

    with pytest.raises(ValueError, match="same ordered logical features"):
        validate_registry_pair(primary, secondary)
