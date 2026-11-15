"""Presentation state for pipeline runs, independent of Streamlit."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from data_quality_agent.persistence.models import IncidentAction, RunState, RunSummary
from data_quality_agent.simulator.models import (
    EventKind,
    PipelineEvent,
    PipelineRun,
    PipelineStatus,
    StageName,
    StageStatus,
)


class StepState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING = "waiting"


STEP_LABELS = {
    StageName.INGESTION: "Ingestão",
    StageName.TRANSFORMATION: "Transformação",
    StageName.DATA_QUALITY: "Data Quality determinístico",
    StageName.AGENT_INTERVENTION: "Intervenção dos agentes",
    StageName.REVALIDATION: "Revalidação",
    StageName.DELIVERY: "Carregamento em SQLite",
}

STEP_ICONS = {
    StepState.QUEUED: "⚪",
    StepState.RUNNING: "🟡",
    StepState.SUCCEEDED: "✅",
    StepState.FAILED: "❌",
    StepState.SKIPPED: "⏭️",
    StepState.WAITING: "⏸️",
}

STEP_STATE_LABELS = {
    StepState.QUEUED: "Em fila",
    StepState.RUNNING: "Em execução",
    StepState.SUCCEEDED: "Concluída",
    StepState.FAILED: "Falhou",
    StepState.SKIPPED: "Ignorada",
    StepState.WAITING: "A aguardar agentes",
}

RUN_BADGES = {
    PipelineStatus.SUCCEEDED: "✅ Concluída",
    PipelineStatus.BLOCKED: "⛔ Bloqueada",
    PipelineStatus.FAILED: "❌ Falhou",
}

_FINISHED_STATES = {
    StageStatus.SUCCEEDED: StepState.SUCCEEDED,
    StageStatus.FAILED: StepState.FAILED,
    StageStatus.SKIPPED: StepState.SKIPPED,
    StageStatus.PENDING: StepState.WAITING,
}


@dataclass
class StepView:
    stage: StageName
    state: StepState = StepState.QUEUED
    logs: list[PipelineEvent] = field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def label(self) -> str:
        return STEP_LABELS[self.stage]

    @property
    def icon(self) -> str:
        return STEP_ICONS[self.state]

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at is None or self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()


class RunTracker:
    """Rebuild each step's state and logs from the events of one run."""

    def __init__(self) -> None:
        self.events: list[PipelineEvent] = []
        self._steps = {stage: StepView(stage) for stage in StageName}

    @classmethod
    def from_events(cls, events: list[PipelineEvent]) -> RunTracker:
        tracker = cls()
        for event in events:
            tracker.apply(event)
        return tracker

    def apply(self, event: PipelineEvent) -> None:
        self.events.append(event)
        if event.stage is None:
            return
        step = self._steps[event.stage]
        if event.kind == EventKind.STAGE_STARTED:
            step.state = StepState.RUNNING
            step.started_at = event.timestamp
            step.finished_at = None
        elif event.kind == EventKind.STAGE_FINISHED and event.status is not None:
            step.state = _FINISHED_STATES[event.status]
            if step.started_at is not None:
                step.finished_at = event.timestamp
        elif event.kind == EventKind.LOG:
            step.logs.append(event)

    @property
    def steps(self) -> list[StepView]:
        return list(self._steps.values())

    @property
    def current_step(self) -> StepView | None:
        return next((step for step in self.steps if step.state == StepState.RUNNING), None)

    @property
    def elapsed_seconds(self) -> float:
        if len(self.events) < 2:
            return 0.0
        return (self.events[-1].timestamp - self.events[0].timestamp).total_seconds()


@dataclass(frozen=True)
class RunGroup:
    primary: RunSummary
    secondary: list[RunSummary] = field(default_factory=list)

    @property
    def latest(self) -> RunSummary:
        return self.secondary[-1] if self.secondary else self.primary

    @property
    def status(self) -> RunState:
        return self.latest.status

    @property
    def run_ids(self) -> list[str]:
        return [self.primary.run_id, *(run.run_id for run in self.secondary)]


def group_runs(summaries: list[RunSummary], actions: list[IncidentAction]) -> list[RunGroup]:
    """Only automatic attempts share a history item; manual corrections remain independent."""
    by_id = {summary.run_id: summary for summary in summaries}
    parents: dict[str, str] = {}
    for action in actions:
        child = action.result_run_id or action.execution_run_id
        if child is None or child not in by_id:
            continue
        if action.source_run_id not in by_id:
            raise ValueError("Uma tentativa automática não tem a execução de origem.")
        if child in parents and parents[child] != action.source_run_id:
            raise ValueError("Uma tentativa automática tem mais de uma execução de origem.")
        parents[child] = action.source_run_id
    grouped: dict[str, list[RunSummary]] = {}
    for summary in summaries:
        root = summary.run_id
        visited: set[str] = set()
        while root in parents:
            if root in visited:
                raise ValueError("As tentativas automáticas contêm uma ligação circular.")
            visited.add(root)
            root = parents[root]
        grouped.setdefault(root, []).append(summary)
    groups = [
        RunGroup(
            primary=by_id[root],
            secondary=sorted(
                (summary for summary in runs if summary.run_id != root),
                key=lambda summary: summary.started_at,
            ),
        )
        for root, runs in grouped.items()
    ]
    return sorted(groups, key=lambda group: group.latest.started_at, reverse=True)


@dataclass(frozen=True)
class RunMetrics:
    records_received: int
    records_loaded: int
    rules_failed: int
    rows_affected: int
    delay_minutes: int
    duration_seconds: float


def run_metrics(result: PipelineRun) -> RunMetrics:
    affected = {index for finding in result.findings for index in finding.row_indexes}
    return RunMetrics(
        records_received=len(result.input_records),
        records_loaded=len(result.output_records),
        rules_failed=len(result.findings),
        rows_affected=len(affected),
        delay_minutes=result.delay_minutes,
        duration_seconds=RunTracker.from_events(result.events).elapsed_seconds,
    )


def format_log_line(event: PipelineEvent) -> str:
    time = event.timestamp.astimezone().strftime("%H:%M:%S.%f")[:-3]
    marker = "[simulador] " if event.simulation_only else ""
    return f"{time}  {event.level.value.upper():<7}  {marker}{event.message}"


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return ""
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    return f"{seconds:.1f} s"
