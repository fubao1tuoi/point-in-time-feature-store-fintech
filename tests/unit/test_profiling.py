import csv
from pathlib import Path

from pit_feature_store.profiling import (
    build_checksum_manifest,
    build_report,
    profile_csv,
    render_markdown,
    sha256_file,
)


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_profile_csv_detects_key_time_target_and_amount_properties(tmp_path: Path) -> None:
    source = tmp_path / "train_transaction.csv"
    _write_csv(
        source,
        [
            {
                "TransactionID": 1,
                "isFraud": 0,
                "TransactionDT": 0,
                "TransactionAmt": 10.0,
                "ProductCD": "W",
            },
            {
                "TransactionID": 2,
                "isFraud": 1,
                "TransactionDT": 86_401,
                "TransactionAmt": 20.0,
                "ProductCD": "C",
            },
            {
                "TransactionID": 2,
                "isFraud": 0,
                "TransactionDT": 86_400,
                "TransactionAmt": -1.0,
                "ProductCD": "C",
            },
        ],
    )

    profile = profile_csv(source, block_size=256)

    assert profile["row_count"] == 3
    assert profile["column_count"] == 5
    assert profile["checks"]["transaction_id_unique_count"] == 2
    assert profile["checks"]["duplicate_transaction_id_count"] == 1
    assert profile["checks"]["transaction_dt_monotonic_non_decreasing"] is False
    assert profile["checks"]["negative_transaction_amount_count"] == 1
    assert profile["columns"]["isFraud"]["cardinality"] == 2
    assert len(profile["relative_day_profile"]) == 2


def test_render_markdown_contains_core_sections(tmp_path: Path) -> None:
    transaction = tmp_path / "train_transaction.csv"
    identity = tmp_path / "train_identity.csv"
    test_transaction = tmp_path / "test_transaction.csv"
    test_identity = tmp_path / "test_identity.csv"
    _write_csv(
        transaction,
        [
            {
                "TransactionID": 1,
                "isFraud": 1,
                "TransactionDT": 1,
                "TransactionAmt": 100.0,
            }
        ],
    )
    _write_csv(identity, [{"TransactionID": 1, "DeviceType": "desktop"}])
    _write_csv(
        test_transaction,
        [{"TransactionID": 2, "TransactionDT": 2, "TransactionAmt": 50.0}],
    )
    _write_csv(test_identity, [{"TransactionID": 2, "DeviceType": "mobile"}])

    report = build_report(
        {
            "train_transaction": profile_csv(transaction, block_size=128),
            "train_identity": profile_csv(identity, block_size=128),
            "test_transaction": profile_csv(test_transaction, block_size=128),
            "test_identity": profile_csv(test_identity, block_size=128),
        }
    )
    markdown = render_markdown(report)

    assert "# IEEE-CIS Dataset Audit Summary" in markdown
    assert "Target and temporal profile" in markdown
    assert "Identity coverage" in markdown
    assert "Fraud: 1" in markdown
    assert report["transaction_schema_comparison"]["schemas_compatible"] is True


def test_checksum_manifest_uses_file_content_and_metadata(tmp_path: Path) -> None:
    source = tmp_path / "train_transaction.csv"
    source.write_bytes(b"TransactionID,TransactionAmt\n1,10.0\n")

    manifest = build_checksum_manifest({"train_transaction": source})
    entry = manifest["files"][0]

    assert manifest["algorithm"] == "sha256"
    assert entry["source_name"] == "train_transaction"
    assert entry["file_name"] == source.name
    assert entry["size_bytes"] == source.stat().st_size
    assert entry["sha256"] == sha256_file(source, chunk_size=3)
    assert len(entry["sha256"]) == 64


def test_checksum_changes_when_file_content_changes(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    source.write_bytes(b"first")
    first = sha256_file(source)
    source.write_bytes(b"second")

    assert sha256_file(source) != first


def test_checksum_rejects_invalid_chunk_size(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    source.write_bytes(b"content")

    try:
        sha256_file(source, chunk_size=0)
    except ValueError as error:
        assert str(error) == "chunk_size must be greater than zero"
    else:
        raise AssertionError("Expected ValueError for invalid chunk size")
