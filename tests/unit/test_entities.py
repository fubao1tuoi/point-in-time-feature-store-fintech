import pytest

from pit_feature_store.entities import (
    CARD_ADDRESS_ENTITY_PREFIX,
    CARD_ENTITY_PREFIX,
    add_card_address_entity_id,
    add_entity_ids,
    build_card_address_entity_id,
    build_card_entity_id,
    canonicalize_category,
)


def test_entity_id_is_deterministic_and_normalizes_integral_float() -> None:
    first = build_card_address_entity_id(1001, 325)
    second = build_card_address_entity_id(1001.0, 325.0)

    assert first == second
    assert first is not None
    assert first.startswith(CARD_ADDRESS_ENTITY_PREFIX)


def test_entity_id_changes_when_a_component_changes() -> None:
    assert build_card_address_entity_id(1001, 325) != build_card_address_entity_id(1001, 326)


def test_strict_null_policy_does_not_create_a_shared_missing_entity() -> None:
    assert build_card_address_entity_id(1001, None) is None
    assert build_card_address_entity_id(None, 325) is None


def test_entity_id_does_not_expose_raw_components() -> None:
    entity_id = build_card_address_entity_id(123456, 789)

    assert entity_id is not None
    assert "123456" not in entity_id
    assert "789" not in entity_id


def test_add_entity_id_does_not_mutate_input_row() -> None:
    row = {"TransactionID": 1, "card1": 1001, "addr1": 325}
    enriched = add_card_address_entity_id(row)

    assert "card_address_entity_id" not in row
    assert enriched["card_address_entity_id"] == build_card_address_entity_id(1001, 325)


def test_canonicalizer_rejects_non_finite_values() -> None:
    with pytest.raises(ValueError):
        canonicalize_category(float("nan"))


def test_card_entity_id_is_available_without_address() -> None:
    entity_id = build_card_entity_id(1001)

    assert entity_id is not None
    assert entity_id.startswith(CARD_ENTITY_PREFIX)
    assert build_card_entity_id(None) is None


def test_add_entity_ids_builds_both_views_when_primary_is_available() -> None:
    enriched = add_entity_ids({"TransactionID": 1, "card1": 1001, "addr1": 325})

    assert enriched["card_address_entity_id"] == build_card_address_entity_id(1001, 325)
    assert enriched["card_entity_id"] == build_card_entity_id(1001)
    assert enriched["has_card_address_entity"] == 1
    assert enriched["entity_resolution_level"] == "card_address"


def test_add_entity_ids_routes_missing_address_to_card_view() -> None:
    enriched = add_entity_ids({"TransactionID": 2, "card1": 1001, "addr1": None})

    assert enriched["card_address_entity_id"] is None
    assert enriched["card_entity_id"] == build_card_entity_id(1001)
    assert enriched["has_card_address_entity"] == 0
    assert enriched["entity_resolution_level"] == "card_only"


def test_add_entity_ids_marks_missing_card_as_unresolved() -> None:
    enriched = add_entity_ids({"TransactionID": 3, "card1": None, "addr1": 325})

    assert enriched["card_address_entity_id"] is None
    assert enriched["card_entity_id"] is None
    assert enriched["has_card_address_entity"] == 0
    assert enriched["entity_resolution_level"] == "unresolved"
