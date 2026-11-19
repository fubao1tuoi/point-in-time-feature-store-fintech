"""Tests for the one-line JSON logging contract used by Cloud Run Jobs."""

import json
from datetime import date

from pit_feature_store.structured_logging import emit_structured_log


def test_emit_structured_log_is_valid_single_line_json(capsys) -> None:
    event = emit_structured_log(
        run_id="daily-2017-01-08",
        stage="silver",
        status="success",
        environment="dev",
        processing_date=date(2017, 1, 8),
        version=1,
        row_count=144,
        duration_seconds=12.5,
    )

    output = capsys.readouterr().out.strip()
    payload = json.loads(output)
    assert "\n" not in output
    assert payload["run_id"] == "daily-2017-01-08"
    assert payload["stage"] == "silver"
    assert payload["processing_date"] == "2017-01-08"
    assert payload["row_count"] == 144
    assert event.status == "success"
