"""Versioned evaluation expectations and machine-readable reports."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from data_quality_agent.persistence.models import ActionName, IncidentState, ModelCall
from data_quality_agent.simulator.models import PipelineStatus, QualityStatus


class AgentExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_status: IncidentState
    expected_action: ActionName | None
    output_count: int
    required_roles: list[str] = Field(default_factory=list)


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    scenario_file: str
    pipeline_status: PipelineStatus
    quality_status: QualityStatus
    output_count: int
    required_findings: list[str] = Field(default_factory=list)
    agent: AgentExpectation | None = None


class EvaluationCheck(BaseModel):
    name: str
    passed: bool
    expected: Any
    actual: Any


class EvaluationCaseResult(BaseModel):
    scenario_id: str
    passed: bool
    run_id: str | None
    checks: list[EvaluationCheck]
    error_type: str | None = None
    duration_ms: float | None = None
    model_calls: list[ModelCall] = Field(default_factory=list)
    control_database: str | None = None


class EvaluationReport(BaseModel):
    schema_version: Literal[1] = 1
    mode: Literal["deterministic", "agents"]
    model_name: str | None = None
    started_at: datetime
    finished_at: datetime
    passed_cases: int
    failed_cases: int
    results: list[EvaluationCaseResult]
