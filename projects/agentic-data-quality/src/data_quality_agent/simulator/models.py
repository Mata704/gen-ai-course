from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FaultKind(str, Enum):
    NULL_VALUE = "null_value"
    DUPLICATE_ROW = "duplicate_row"
    SET_VALUE = "set_value"
    DROP_COLUMN = "drop_column"
    ADD_COLUMN = "add_column"
    DELAY = "delay"
    DROP_ROWS = "drop_rows"
    SOURCE_UNAVAILABLE = "source_unavailable"
    PIPELINE_FAILURE = "pipeline_failure"


class RuleKind(str, Enum):
    SCHEMA = "schema"
    NOT_NULL = "not_null"
    UNIQUE = "unique"
    NUMERIC_RANGE = "numeric_range"
    ALLOWED_VALUES = "allowed_values"
    REFERENTIAL_INTEGRITY = "referential_integrity"
    MIN_ROWS = "min_rows"
    FRESHNESS = "freshness"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PipelineStatus(str, Enum):
    SUCCEEDED = "succeeded"
    BLOCKED = "blocked"
    FAILED = "failed"


class StageName(str, Enum):
    INGESTION = "ingestion"
    TRANSFORMATION = "transformation"
    DATA_QUALITY = "data_quality"
    AGENT_INTERVENTION = "agent_intervention"
    REVALIDATION = "revalidation"
    DELIVERY = "delivery"


class StageStatus(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class QualityStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_RUN = "not_run"


class EventKind(str, Enum):
    STAGE_STARTED = "stage_started"
    STAGE_FINISHED = "stage_finished"
    LOG = "log"


class LogLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Fault(StrictModel):
    kind: FaultKind
    row_index: int | None = Field(default=None, ge=0)
    field: str | None = None
    value: Any = None
    delay_minutes: int | None = Field(default=None, ge=0)
    count: int | None = Field(default=None, ge=1)


class Scenario(StrictModel):
    scenario_id: str = Field(min_length=1)
    description: str
    pipeline_id: str = Field(min_length=1)
    seed: int = 0
    faults: list[Fault] = Field(default_factory=list)


class QualityRule(StrictModel):
    rule_id: str = Field(min_length=1)
    name: str
    kind: RuleKind
    severity: Severity
    field: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    allowed_values: list[str] = Field(default_factory=list)
    reference_values: list[str] = Field(default_factory=list)
    minimum_count: int | None = Field(default=None, ge=0)
    maximum_delay_minutes: int | None = Field(default=None, ge=0)
    # Filled when a pipeline is resolved: a general rule shared by every pipeline, or its own rule.
    origin: Literal["general", "pipeline"] = "pipeline"
    # Why this pipeline changed a general rule.
    adjustment_reason: str | None = None


class GeneralRuleLibrary(StrictModel):
    """Rules every pipeline gets by default (rules/general.json)."""

    description: str
    rules: list[QualityRule]


class GeneralRuleAdjustment(StrictModel):
    """How one pipeline changes a general rule; the reason is mandatory and kept with the rule."""

    reason: str = Field(min_length=1)
    enabled: bool = True
    severity: Severity | None = None
    minimum_count: int | None = Field(default=None, ge=0)
    maximum_delay_minutes: int | None = Field(default=None, ge=0)


class PipelineConfig(StrictModel):
    """A pipeline definition file: adjustments to the general rules plus the pipeline's own rules."""

    pipeline_id: str = Field(min_length=1)
    name: str
    dataset_file: str
    # Where the data comes from in the producers' platform (served by the MCP server).
    source_system: str | None = None
    source_dataset: str | None = None
    expected_columns: list[str]
    general_rules: dict[str, GeneralRuleAdjustment] = Field(default_factory=dict)
    rules: list[QualityRule] = Field(default_factory=list)


class PipelineDefinition(StrictModel):
    """A pipeline with its effective rules (general ones already adjusted), as stored with each run."""

    pipeline_id: str = Field(min_length=1)
    name: str
    dataset_file: str
    source_system: str | None = None
    source_dataset: str | None = None
    expected_columns: list[str]
    rules: list[QualityRule]
    # General rules this pipeline switched off, with the reason.
    disabled_general_rules: dict[str, str] = Field(default_factory=dict)


class QualityFinding(StrictModel):
    rule_id: str
    rule_name: str
    severity: Severity
    message: str
    affected_rows: int = Field(ge=0)
    row_indexes: list[int] = Field(default_factory=list)


class StageResult(StrictModel):
    name: StageName
    status: StageStatus


class PipelineEvent(StrictModel):
    """Progress notification emitted while a run executes, in stage order."""

    sequence: int = Field(ge=0)
    run_id: str
    timestamp: datetime
    kind: EventKind
    stage: StageName | None = None
    status: StageStatus | None = None
    level: LogLevel = LogLevel.INFO
    message: str
    # Simulator bookkeeping (scenario and injected faults): shown to people, never to agents.
    simulation_only: bool = False


class PipelineIncident(StrictModel):
    run_id: str
    scenario_id: str
    pipeline_id: str
    kind: Literal["data_quality", "pipeline_failure"]
    status: Literal["pending_analysis"] = "pending_analysis"
    summary: str
    failed_rule_ids: list[str] = Field(default_factory=list)


class PipelineRun(StrictModel):
    run_id: str
    scenario_id: str
    pipeline_id: str
    seed: int
    pipeline_status: PipelineStatus
    quality_status: QualityStatus
    record_count: int = Field(ge=0)
    delay_minutes: int = Field(ge=0)
    observed_columns: list[str]
    findings: list[QualityFinding] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    records: list[dict[str, Any]] = Field(default_factory=list)
    input_records: list[dict[str, Any]] = Field(default_factory=list)
    stages: list[StageResult]
    destination: str
    output_records: list[dict[str, Any]] = Field(default_factory=list)
    incident: PipelineIncident | None = None
    events: list[PipelineEvent] = Field(default_factory=list)
