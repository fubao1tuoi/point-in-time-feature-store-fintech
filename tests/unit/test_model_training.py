"""Contract tests for comparable raw and raw-plus-PIT model variants."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from pit_feature_store.model_training import (
    ModelTrainingConfig,
    feature_columns_for_variant,
    load_model_training_config,
    resolve_feature_groups,
)

CONFIG = Path("configs/model_training.yaml")


def test_project_config_resolves_expected_feature_groups() -> None:
    config = load_model_training_config(CONFIG)
    groups = resolve_feature_groups(config)

    assert len(groups["raw"]) == 15
    assert len(groups["categorical"]) == 14
    assert len(groups["pit"]) == 20
    assert len(groups["pit_missing"]) == 20
    assert len(set(groups["raw"] + groups["pit"] + groups["pit_missing"])) == 55


def test_variants_select_raw_15_and_raw_plus_pit_55() -> None:
    config = load_model_training_config(CONFIG)
    groups = resolve_feature_groups(config)
    variants = {variant.name: variant for variant in config.variants}

    assert len(feature_columns_for_variant(variants["raw_baseline"], groups)) == 15
    mvp = feature_columns_for_variant(variants["raw_plus_pit_mvp"], groups)
    assert len(mvp) == 55
    assert any(name.startswith("card_addr_") for name in mvp)
    assert any(name.startswith("card_") and not name.startswith("card_addr_") for name in mvp)


def test_config_rejects_missing_comparable_variant() -> None:
    content = load_model_training_config(CONFIG).model_dump(mode="json")
    content["variants"] = [content["variants"][0], content["variants"][0] | {"name": "raw_2"}]

    with pytest.raises(ValidationError, match="raw-plus-PIT"):
        ModelTrainingConfig.model_validate(content)
