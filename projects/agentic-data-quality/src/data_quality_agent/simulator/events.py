"""Progress events and stage transitions for a simulated run."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from data_quality_agent.simulator.models import (
    EventKind,
    LogLevel,
    PipelineEvent,
    PipelineRun,
    StageName,
    StageResult,
    StageStatus,
)

EventListener = Callable[[PipelineEvent], None]
STAGE_ORDER = list(StageName)


class RunRecorder:
    """Track stage transitions in pipeline order and publish them as events."""

    def __init__(
        self,
        result: PipelineRun,
        stages: dict[StageName, StageResult],
        listener: EventListener | None,
    ) -> None:
        self._result = result
        self._stages = stages
        self._listener = listener
        self._finished: set[StageName] = set()
        self._current: StageName | None = None

    def start(self, stage: StageName) -> None:
        self._finish_earlier(stage)
        self._current = stage
        self._emit(EventKind.STAGE_STARTED, f"Started {stage.value}.", stage=stage)

    def log(
        self, message: str, level: LogLevel = LogLevel.INFO, *, simulation_only: bool = False,
    ) -> None:
        self._emit(
            EventKind.LOG, message, stage=self._current, level=level,
            simulation_only=simulation_only,
        )

    def finish(self, stage: StageName, status: StageStatus) -> None:
        self._finish_earlier(stage)
        self._stages[stage].status = status
        self._finished.add(stage)
        self._current = None
        self._emit(
            EventKind.STAGE_FINISHED, f"Finished {stage.value}: {status.value}.",
            stage=stage, status=status,
        )

    def abort(self, message: str) -> None:
        """Report an unexpected error in the running stage and close the run."""
        if self._current is not None:
            self.log(message, LogLevel.ERROR)
            self.finish(self._current, StageStatus.FAILED)
        self.close()

    def close(self) -> None:
        for stage in STAGE_ORDER:
            if stage not in self._finished:
                self.finish(stage, self._stages[stage].status)

    def _finish_earlier(self, stage: StageName) -> None:
        for earlier in STAGE_ORDER[:STAGE_ORDER.index(stage)]:
            if earlier not in self._finished:
                self.finish(earlier, self._stages[earlier].status)

    def _emit(
        self,
        kind: EventKind,
        message: str,
        *,
        stage: StageName | None = None,
        status: StageStatus | None = None,
        level: LogLevel = LogLevel.INFO,
        simulation_only: bool = False,
    ) -> None:
        event = PipelineEvent(
            sequence=len(self._result.events),
            run_id=self._result.run_id,
            timestamp=datetime.now(timezone.utc),
            kind=kind,
            stage=stage,
            status=status,
            level=level,
            message=message,
            simulation_only=simulation_only,
        )
        self._result.events.append(event)
        if self._listener is not None:
            self._listener(event)
