import csv
import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import pytest

from pit_feature_store.bronze import run_bronze_ingestion
from pit_feature_store.entities import (
    build_card_address_entity_id,
    build_card_entity_id,
)
from pit_feature_store.silver import (
    _duplicate_policy,
    entity_expressions,
    normalize_identity_column,
    run_silver_transformation,
)


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_config(project_root: Path) -> None:
    configs = project_root / "configs"
    configs.mkdir(parents=True)
    (configs / "project.yaml").write_text(
        """
project:
  name: silver-test
  environment: test
  timezone: UTC
  synthetic_epoch: "2017-01-01T00:00:00Z"
storage:
  raw: data/raw
  bronze: data/bronze
  silver: data/silver
  offline_store: data/offline_store
processing:
  transaction_time_offset_column: TransactionDT
  transaction_time_offset_unit: seconds
  observation_time_column: event_time
  transaction_id_column: TransactionID
  target_column: isFraud
""".strip(),
        encoding="utf-8",
    )
    (configs / "sources.yaml").write_text(
        """
version: 1
sources:
  train_transaction:
    path: data/raw/train_transaction.csv
    file_format: csv
    split: train
    table: transaction
    bronze_output: train_transaction
    primary_key: TransactionID
    required_columns: [TransactionID, isFraud, TransactionDT, TransactionAmt]
  train_identity:
    path: data/raw/train_identity.csv
    file_format: csv
    split: train
    table: identity
    bronze_output: train_identity
    join_key: TransactionID
    optional: true
    required_columns: [TransactionID]
  test_transaction:
    path: data/raw/test_transaction.csv
    file_format: csv
    split: test
    table: transaction
    bronze_output: test_transaction
    primary_key: TransactionID
    required_columns: [TransactionID, TransactionDT, TransactionAmt]
  test_identity:
    path: data/raw/test_identity.csv
    file_format: csv
    split: test
    table: identity
    bronze_output: test_identity
    join_key: TransactionID
    optional: true
    required_columns: [TransactionID]
""".strip(),
        encoding="utf-8",
    )


def _prepare_project(project_root: Path) -> None:
    _write_config(project_root)
    raw = project_root / "data/raw"
    _write_csv(
        raw / "train_transaction.csv",
        [
            {
                "TransactionID": "1",
                "isFraud": "0",
                "TransactionDT": "86400",
                "TransactionAmt": "10.50",
                "ProductCD": "W",
                "card1": "1001.0",
                "addr1": "325.0",
            },
            {
                "TransactionID": "2",
                "isFraud": "1",
                "TransactionDT": "90000",
                "TransactionAmt": "20.00",
                "ProductCD": "C",
                "card1": "1001",
                "addr1": "",
            },
        ],
    )
    _write_csv(
        raw / "train_identity.csv",
        [{"TransactionID": "1", "id_12": "Found", "DeviceType": "desktop"}],
    )
    _write_csv(
        raw / "test_transaction.csv",
        [
            {
                "TransactionID": "3",
                "TransactionDT": "172800",
                "TransactionAmt": "30.00",
                "ProductCD": "W",
                "card1": "2002",
                "addr1": "100",
            }
        ],
    )
    _write_csv(
        raw / "test_identity.csv",
        [{"TransactionID": "3", "id-12": "NotFound", "DeviceType": "mobile"}],
    )


def test_entity_sql_matches_python_implementation() -> None:
    expressions = entity_expressions()
    result = duckdb.sql(
        f"""
        SELECT
            {expressions["card_entity_id"]},
            {expressions["card_address_entity_id"]}
        FROM (SELECT '1001.0' AS card1, '325.0' AS addr1)
        """
    ).fetchone()

    assert result == (
        build_card_entity_id(1001),
        build_card_address_entity_id(1001, 325),
    )
    assert normalize_identity_column("id-12") == "id_12"


def test_silver_builds_canonical_joined_partitioned_dataset(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    reports = tmp_path / "reports/generated"
    bronze_manifest = reports / "bronze_ingestion_manifest.json"
    silver_manifest = reports / "silver_build_manifest.json"
    run_bronze_ingestion(project_root=tmp_path, manifest_path=bronze_manifest)

    first = run_silver_transformation(
        project_root=tmp_path,
        manifest_path=silver_manifest,
        bronze_manifest_path=bronze_manifest,
        memory_limit="1GB",
        threads=1,
    )
    dataset = ds.dataset(
        tmp_path / "data/silver/transactions",
        format="parquet",
        partitioning="hive",
    )
    rows = sorted(dataset.to_table().to_pylist(), key=lambda row: row["TransactionID"])

    assert len(rows) == 3
    assert rows[0]["TransactionAmt"] == 10.5
    assert rows[0]["event_time"].isoformat().startswith("2017-01-02T00:00:00")
    assert rows[0]["has_identity"] is True
    assert rows[1]["has_identity"] is False
    assert rows[0]["card_entity_id"] == build_card_entity_id(1001)
    assert rows[0]["card_address_entity_id"] == build_card_address_entity_id(1001, 325)
    assert rows[1]["card_address_entity_id"] is None
    assert rows[1]["entity_resolution_level"] == "card_only"
    assert rows[2]["id_12"] == "NotFound"
    assert first["quality_metrics"]["row_count_by_split"] == {"train": 2, "test": 1}

    # Re-ingestion changes operational run/timestamp metadata, but not business data.
    run_bronze_ingestion(project_root=tmp_path, manifest_path=bronze_manifest)
    second = run_silver_transformation(
        project_root=tmp_path,
        manifest_path=silver_manifest,
        bronze_manifest_path=bronze_manifest,
        memory_limit="1GB",
        threads=1,
    )

    assert second["matches_previous_run"] is True
    assert second["semantic_fingerprint"] == first["semantic_fingerprint"]
    assert json.loads(silver_manifest.read_text(encoding="utf-8"))["status"] == "success"


def test_duplicate_policy_rejects_conflicting_transaction_rows(tmp_path: Path) -> None:
    path = tmp_path / "duplicates.parquet"
    pq.write_table(
        pa.table(
            {
                "TransactionID": ["1", "1"],
                "TransactionAmt": ["10", "20"],
                "_source_row_number": [1, 2],
            }
        ),
        path,
    )

    with pytest.raises(ValueError, match="Conflicting duplicate"):
        _duplicate_policy(duckdb.connect(), path, "TransactionID")
