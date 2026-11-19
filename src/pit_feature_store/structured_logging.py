"""Small JSON logging contract shared by local and cloud batch entrypoints."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StructuredLogEvent(BaseModel):
    """One machine-readable pipeline event written as a single JSON line."""

    model_config = ConfigDict(extra="forbid")

    timestamp_utc: datetime
    run_id: str = Field(min_length=1)
    stage: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    status: Literal["started", "success", "failed", "info"]
    environment: str = Field(min_length=1)
    processing_date: date | None = None
    version: int | None = Field(default=None, ge=1)
    row_count: int | None = Field(default=None, ge=0)
    duration_seconds: float | None = Field(default=None, ge=0)
    message: str | None = None
    extra: dict[str, object] = Field(default_factory=dict)


def emit_structured_log(
    *,
    run_id: str,
    stage: str,
    status: Literal["started", "success", "failed", "info"],
    environment: str,
    processing_date: date | None = None,
    version: int | None = None,
    row_count: int | None = None,
    duration_seconds: float | None = None,
    message: str | None = None,
    extra: dict[str, object] | None = None,
) -> StructuredLogEvent:
    """Validate and emit one event to stdout for Cloud Logging ingestion."""
    event = StructuredLogEvent(
        timestamp_utc=datetime.now(UTC),
        run_id=run_id,
        stage=stage,
        status=status,
        environment=environment,
        processing_date=processing_date,
        version=version,
        row_count=row_count,
        duration_seconds=duration_seconds,
        message=message,
        extra=extra or {},
    )
    print(json.dumps(event.model_dump(mode="json"), ensure_ascii=False), flush=True)
    return event
