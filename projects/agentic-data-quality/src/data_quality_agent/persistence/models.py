"""Models returned by the control database repositories."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from data_quality_agent.simulator.models import PipelineIncident, QualityStatus

RunState = Literal["running", "succeeded", "blocked", "failed"]
RecordStep = Literal["ingested", "transformed"]


class RunSummary(BaseModel):
    run_id: str
    pipeline_id: str
    pipeline_version: str
    scenario_id: str
    status: RunState
    quality_status: QualityStatus
    record_count: int
    delay_minutes: int
    observed_columns: list[str]
    errors: list[str]
    started_at: datetime
    finished_at: datetime | None


class StoredIncident(PipelineIncident):
    opened_at: datetime


class ToolCall(BaseModel):
    call_id: int
    called_at: datetime
    agent: str
    tool: str
    source: Literal["local", "mcp"] | None
    arguments: dict[str, Any]
    run_id: str | None
    outcome: Literal["ok", "error", "blocked"]
    detail: str
    duration_ms: int
