"""Models returned by the control database repositories."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from data_quality_agent.simulator.models import PipelineIncident, QualityStatus

RunState = Literal["running", "succeeded", "blocked", "failed"]
RecordStep = Literal["ingested", "transformed"]
IncidentState = Literal[
    "awaiting_correction", "investigating", "correcting", "resolved", "unresolved", "analysis_failed",
]


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


class IncidentWorkflow(BaseModel):
    incident_id: str
    latest_run_id: str
    status: IncidentState
    updated_at: datetime


class AgentSession(BaseModel):
    session_id: str
    run_id: str
    status: Literal["running", "completed", "failed"]
    started_at: datetime
    finished_at: datetime | None
    outcome: dict[str, Any] | None
    error: str | None


class AgentStep(BaseModel):
    timestamp: datetime
    agent: str
    kind: str
    message: str


class ModelCall(BaseModel):
    call_id: int | None = None
    session_id: str | None
    run_id: str
    agent: str
    model_name: str
    provider: str
    started_at: datetime
    duration_ms: float
    outcome: Literal["ok", "error"]
    input_tokens: int | None
    output_tokens: int | None


ActionName = Literal["retry_ingestion", "quarantine_failed_records"]


class IncidentAction(BaseModel):
    action_id: int
    incident_id: str
    source_run_id: str
    action: ActionName
    requested_by: str
    status: Literal["running", "executed", "failed"]
    detail: str
    result_run_id: str | None
    execution_run_id: str | None
    request: dict[str, Any]
    requested_at: datetime
    finished_at: datetime | None


class FailedRecord(BaseModel):
    """A failed row stored separately from approved data. Never given to the agents."""

    source_run_id: str
    position: int
    action_id: int
    rule_ids: list[str]
    record: dict[str, Any]
    status: Literal["held", "released", "discarded"]


class FailedRecordApproval(BaseModel):
    approval_id: int
    source_run_id: str
    position: int
    target_status: Literal["released", "discarded"]
    reason: str
    requested_by: str
    requester_attested: bool
    decided_by: str | None
    decider_attested: bool
    status: Literal["pending", "executed", "rejected"]
    requested_at: datetime
    finished_at: datetime | None


RuleThreshold = Literal["minimum_count", "maximum_delay_minutes"]


class PipelineRuleApproval(BaseModel):
    approval_id: int
    incident_id: str
    pipeline_id: str
    rule_id: str
    attribute: RuleThreshold
    previous_value: int
    proposed_value: int
    reason: str
    requested_by: str
    requester_attested: bool
    decided_by: str | None
    decider_attested: bool
    status: Literal["pending", "executed", "rejected"]
    requested_at: datetime
    finished_at: datetime | None


class IncidentMemory(BaseModel):
    memory_id: int
    pipeline_id: str
    content: str
    source_ref: str
    created_by: str
    created_at: datetime
    valid_until: datetime
