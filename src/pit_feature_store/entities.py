"""Deterministic surrogate entity identifiers for IEEE-CIS transactions."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

CARD_ADDRESS_ENTITY_VERSION = 1
CARD_ADDRESS_ENTITY_PREFIX = "cae_v1_"
CARD_ADDRESS_ENTITY_COLUMNS = ("card1", "addr1")
CARD_ENTITY_VERSION = 1
CARD_ENTITY_PREFIX = "ce_v1_"
CARD_ENTITY_COLUMNS = ("card1",)


def canonicalize_category(value: Any) -> str:
    """Return a stable representation for an encoded categorical value.

    PyArrow/CSV/Parquet readers may represent the same encoded category as
    either ``1001`` or ``1001.0``. Integral floats are therefore normalized to
    integer strings before hashing.
    """
    if value is None:
        raise ValueError("Entity-key components cannot be null")
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Entity-key components must be finite")
        if value.is_integer():
            return str(int(value))
        return format(value, ".17g")
    return str(value)


def build_card_address_entity_id(card1: Any, addr1: Any) -> str | None:
    """Build the v1 strict entity ID from ``card1`` and ``addr1``.

    The strict null policy returns ``None`` when either component is missing.
    Raw values are not exposed in the resulting identifier.
    """
    if card1 is None or addr1 is None:
        return None
    payload = {
        "card1": canonicalize_category(card1),
        "addr1": canonicalize_category(addr1),
        "version": CARD_ADDRESS_ENTITY_VERSION,
    }
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return f"{CARD_ADDRESS_ENTITY_PREFIX}{digest}"


def build_card_entity_id(card1: Any) -> str | None:
    """Build the v1 secondary entity ID from ``card1``."""
    if card1 is None:
        return None
    payload = {
        "card1": canonicalize_category(card1),
        "version": CARD_ENTITY_VERSION,
    }
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return f"{CARD_ENTITY_PREFIX}{digest}"


def add_card_address_entity_id(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of a row with the selected surrogate entity column."""
    result = dict(row)
    result["card_address_entity_id"] = build_card_address_entity_id(
        row.get("card1"), row.get("addr1")
    )
    return result


def add_entity_ids(row: Mapping[str, Any]) -> dict[str, Any]:
    """Add both entity views and routing metadata without mutating input."""
    result = dict(row)
    card_entity_id = build_card_entity_id(row.get("card1"))
    card_address_entity_id = build_card_address_entity_id(row.get("card1"), row.get("addr1"))
    result.update(
        {
            "card_entity_id": card_entity_id,
            "card_address_entity_id": card_address_entity_id,
            "has_card_address_entity": int(card_address_entity_id is not None),
            "entity_resolution_level": (
                "card_address"
                if card_address_entity_id is not None
                else "card_only"
                if card_entity_id is not None
                else "unresolved"
            ),
            "card_entity_version": CARD_ENTITY_VERSION,
            "card_address_entity_version": CARD_ADDRESS_ENTITY_VERSION,
        }
    )
    return result
