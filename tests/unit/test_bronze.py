import csv
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pit_feature_store.bronze import BRONZE_METADATA_COLUMNS, ingest_source_to_staging
from pit_feature_store.configuration import SourceDefinition


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _transaction_definition() -> SourceDefinition:
    return SourceDefinition(
        path=Path("data/raw/train_transaction.csv"),
        file_format="csv",
        split="train",
        table="transaction",
        bronze_output="train_transaction",
        primary_key="TransactionID",
        required_columns=["TransactionID", "TransactionDT", "TransactionAmt", "isFraud"],
    )


def test_bronze_preserves_lexical_values_and_adds_metadata(tmp_path: Path) -> None:
    source = tmp_path / "train_transaction.csv"
    output = tmp_path / "train_transaction.parquet"
    _write_csv(
        source,
        [
            {
                "TransactionID": "001",
                "TransactionDT": "86400",
                "TransactionAmt": "10.00",
                "isFraud": "0",
                "optional_value": "",
            },
            {
                "TransactionID": "002",
                "TransactionDT": "86401",
                "TransactionAmt": "75.887",
                "isFraud": "1",
                "optional_value": "kept",
            },
        ],
    )
    ingested_at = datetime(2026, 11, 5, tzinfo=UTC)

    result = ingest_source_to_staging(
        source_name="train_transaction",
        definition=_transaction_definition(),
        source_path=source,
        staging_path=output,
        run_id="bronze_test",
        ingested_at=ingested_at,
        block_size_mb=1,
        row_group_size=1,
        progress_every_rows=1,
    )
    table = pq.read_table(output)

    assert result.row_count == 2
    assert table.column("TransactionID").to_pylist() == ["001", "002"]
    assert table.column("TransactionAmt").to_pylist() == ["10.00", "75.887"]
    assert table.column("optional_value").to_pylist() == ["", "kept"]
    assert all(
        pa.types.is_string(table.schema.field(column).type)
        for column in (
            "TransactionID",
            "TransactionDT",
            "TransactionAmt",
            "isFraud",
            "optional_value",
        )
    )
    assert table.column("_source_row_number").to_pylist() == [1, 2]
    assert table.column("_ingestion_run_id").to_pylist() == ["bronze_test", "bronze_test"]
    assert set(BRONZE_METADATA_COLUMNS).issubset(table.column_names)


def test_bronze_rejects_missing_required_column(tmp_path: Path) -> None:
    source = tmp_path / "train_transaction.csv"
    output = tmp_path / "train_transaction.parquet"
    _write_csv(
        source,
        [{"TransactionID": "1", "TransactionDT": "86400", "isFraud": "0"}],
    )

    with pytest.raises(ValueError, match="TransactionAmt"):
        ingest_source_to_staging(
            source_name="train_transaction",
            definition=_transaction_definition(),
            source_path=source,
            staging_path=output,
            run_id="bronze_test",
            ingested_at=datetime(2026, 11, 5, tzinfo=UTC),
            block_size_mb=1,
            row_group_size=100,
            progress_every_rows=100,
        )

    assert not output.exists()


def test_bronze_rejects_source_metadata_collision(tmp_path: Path) -> None:
    source = tmp_path / "train_transaction.csv"
    output = tmp_path / "train_transaction.parquet"
    _write_csv(
        source,
        [
            {
                "TransactionID": "1",
                "TransactionDT": "86400",
                "TransactionAmt": "10",
                "isFraud": "0",
                "_source_name": "unexpected",
            }
        ],
    )

    with pytest.raises(ValueError, match="collides with Bronze metadata"):
        ingest_source_to_staging(
            source_name="train_transaction",
            definition=_transaction_definition(),
            source_path=source,
            staging_path=output,
            run_id="bronze_test",
            ingested_at=datetime(2026, 11, 5, tzinfo=UTC),
            block_size_mb=1,
            row_group_size=100,
            progress_every_rows=100,
        )
