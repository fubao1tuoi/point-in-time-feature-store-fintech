"""Tests for immutable, versioned offline feature Parquet materialization."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from pit_feature_store.offline_store import (
    OfflineMaterializationError,
    materialize_offline_feature_table,
)

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).parent / "fixtures/golden_transactions.csv"
PRIMARY = ROOT / "configs/features/transaction_velocity_v1.yaml"
SECONDARY = ROOT / "configs/features/transaction_velocity_card_v1.yaml"


def _golden_parquet(tmp_path: Path) -> Path:
    output = tmp_path / "silver_golden.parquet"
    connection = duckdb.connect()
    connection.execute(
        f"""
        COPY (
            SELECT TransactionID::BIGINT AS TransactionID,
                   event_time::TIMESTAMPTZ AS event_time,
                   TransactionAmt::DOUBLE AS TransactionAmt,
                   ProductCD, card_entity_id, card_address_entity_id
            FROM read_csv_auto('{GOLDEN.as_posix()}', nullstr='')
        ) TO '{output.as_posix()}' (FORMAT PARQUET)
        """
    )
    connection.close()
    return output


def test_materializes_versioned_parquet_with_complete_feature_schema(
    tmp_path: Path,
) -> None:
    source = _golden_parquet(tmp_path)
    output_root = tmp_path / "offline" / "transaction_features"

    metrics = materialize_offline_feature_table(
        source,
        output_root,
        PRIMARY,
        SECONDARY,
        feature_table_version=1,
    )

    assert metrics.output_path == output_root / "v1"
    assert metrics.output_path.is_dir()
    assert metrics.row_count == metrics.unique_transaction_ids == 10
    assert metrics.feature_column_count == 20
    assert metrics.partition_count == metrics.parquet_file_count == 3
    assert metrics.min_observation_date == "2017-01-01"
    assert metrics.max_observation_date == "2017-01-09"
    assert metrics.parquet_size_bytes > 0
    assert metrics.semantic_fingerprint.startswith("rows=10;xor64=")
    assert metrics.manifest_path.is_file()
    assert {path.parent.name for path in metrics.output_path.rglob("*.parquet")} == {
        "observation_date=2017-01-01",
        "observation_date=2017-01-08",
        "observation_date=2017-01-09",
    }

    connection = duckdb.connect()
    output_glob = (metrics.output_path / "**" / "*.parquet").as_posix()
    columns = [
        row[0]
        for row in connection.execute(
            "DESCRIBE SELECT * "
            f"FROM read_parquet('{output_glob}', hive_partitioning=true)"
        ).fetchall()
    ]
    quality = connection.execute(
        f"""
        SELECT COUNT(*), COUNT(DISTINCT TransactionID),
               MIN(feature_table_version), MAX(feature_table_version),
               MIN(primary_feature_set_version), MAX(secondary_feature_set_version)
        FROM read_parquet('{output_glob}', hive_partitioning=true)
        """
    ).fetchone()
    connection.close()

    assert len(columns) == 29
    assert "observation_date" in columns
    assert len([column for column in columns if column.startswith("card_addr_")]) == 10
    assert len([column for column in columns if column.startswith("card_")]) == 20
    assert quality == (10, 10, 1, 1, 1, 1)
    manifest = json.loads(metrics.manifest_path.read_text(encoding="utf-8"))
    assert manifest["run_id"] == metrics.run_id
    assert manifest["mode"] == "initial"
    assert manifest["source"]["checksum_sha256"]
    assert manifest["feature_table_version"] == 1
    assert manifest["quality"]["row_count"] == 10
    assert manifest["cutoff"]["min_observation_date"] == "2017-01-01"
    assert manifest["cutoff"]["max_observation_date"] == "2017-01-09"


def test_existing_version_is_immutable_and_not_overwritten(tmp_path: Path) -> None:
    source = _golden_parquet(tmp_path)
    output_root = tmp_path / "offline" / "transaction_features"
    first = materialize_offline_feature_table(
        source,
        output_root,
        PRIMARY,
        SECONDARY,
        feature_table_version=1,
    )
    original_files = {
        path.relative_to(first.output_path): path.read_bytes()
        for path in first.output_path.rglob("*.parquet")
    }

    with pytest.raises(OfflineMaterializationError, match="already exists"):
        materialize_offline_feature_table(
            source,
            output_root,
            PRIMARY,
            SECONDARY,
            feature_table_version=1,
        )

    assert {
        path.relative_to(first.output_path): path.read_bytes()
        for path in first.output_path.rglob("*.parquet")
    } == original_files
    assert not list(output_root.glob(".staging_*"))


def test_backfill_is_idempotent_and_replaces_partitions_without_duplicates(
    tmp_path: Path,
) -> None:
    source = _golden_parquet(tmp_path)
    output_root = tmp_path / "offline" / "transaction_features"
    initial = materialize_offline_feature_table(
        source,
        output_root,
        PRIMARY,
        SECONDARY,
        feature_table_version=1,
    )
    cutoff = {
        "start_time": "2017-01-08T00:00:00Z",
        "end_time": "2017-01-09T00:00:00Z",
        "backfill": True,
    }

    first = materialize_offline_feature_table(
        source,
        output_root,
        PRIMARY,
        SECONDARY,
        feature_table_version=1,
        **cutoff,
    )
    second = materialize_offline_feature_table(
        source,
        output_root,
        PRIMARY,
        SECONDARY,
        feature_table_version=1,
        **cutoff,
    )

    assert first.row_count == second.row_count == 8
    assert first.semantic_fingerprint == second.semantic_fingerprint
    assert first.run_id != second.run_id
    assert first.manifest_path.is_file()
    assert second.manifest_path.is_file()

    output_glob = (initial.output_path / "**" / "*.parquet").as_posix()
    connection = duckdb.connect()
    total_rows, unique_ids, jan8_rows = connection.execute(
        f"""
        SELECT COUNT(*), COUNT(DISTINCT TransactionID),
               COUNT(*) FILTER (WHERE observation_date = DATE '2017-01-08')
        FROM read_parquet('{output_glob}', hive_partitioning=true)
        """
    ).fetchone()
    connection.close()

    assert total_rows == unique_ids == 10
    assert jan8_rows == 8
    assert len(list((output_root / "v1" / "manifests").glob("*.json"))) == 3
    assert not list(output_root.glob(".staging_*"))
    assert not list(output_root.glob(".backup_*"))
