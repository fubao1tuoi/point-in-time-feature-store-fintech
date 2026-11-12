"""Unit tests for hardening audit and durable failure records."""

from pathlib import Path

import pytest
import yaml

from pit_feature_store.hardening import (
    AuditLogger,
    _run_stage,
    audit_leakage_contracts,
    load_hardening_config,
    run_hardening,
)


def test_current_project_passes_static_leakage_contracts() -> None:
    config = load_hardening_config(Path("configs/hardening.yaml"))
    result = audit_leakage_contracts(config)

    assert result["status"] == "passed"
    assert result["check_count"] >= 10
    assert all(result["checks"].values())


def test_failed_stage_is_flushed_to_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    logger = AuditLogger(path, "test_run")

    with pytest.raises(RuntimeError, match="deliberate"):
        _run_stage(
            logger,
            "failure_demo",
            lambda: (_ for _ in ()).throw(RuntimeError("deliberate")),
        )

    content = path.read_text(encoding="utf-8")
    assert '"status": "started"' in content
    assert '"status": "failed"' in content
    assert '"error_type": "RuntimeError"' in content


def test_failed_run_preserves_audit_log_and_does_not_publish(tmp_path: Path) -> None:
    config = load_hardening_config(Path("configs/hardening.yaml"))
    broken = config.model_copy(
        update={
            "preprocessing_artifact": tmp_path / "missing_preprocessor.json",
            "output_root": tmp_path / "hardening",
        }
    )
    config_path = tmp_path / "broken.yaml"
    config_path.write_text(
        yaml.safe_dump(broken.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(FileNotFoundError):
        run_hardening(config_path)

    failure_logs = list((tmp_path / "hardening" / "failures").glob("*.jsonl"))
    assert len(failure_logs) == 1
    assert '"status": "failed"' in failure_logs[0].read_text(encoding="utf-8")
    assert not (tmp_path / "hardening" / "v1").exists()
