"""Application service: run a pipeline, keep its history in the control database and deliver
approved data to the separate destination (warehouse) file."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic_ai.models import Model

from data_quality_agent.agents.models import OrchestrationResult
from data_quality_agent.agents.team import AgentExecutionError, AgentTeam
from data_quality_agent.corrections import parse_corrected_batch
from data_quality_agent.persistence.database import DEFAULT_DATABASE, Database
from data_quality_agent.persistence.incidents import IncidentRepository
from data_quality_agent.persistence.models import IncidentState
from data_quality_agent.persistence.repository import RunRepository
from data_quality_agent.simulator.engine import (
    EventListener,
    PipelineSimulator,
    load_pipeline,
    load_scenario,
)
from data_quality_agent.simulator.models import (
    EventKind, LogLevel, PipelineDefinition, PipelineEvent, PipelineRun, PipelineStatus,
    Scenario, StageName, StageStatus,
)
from data_quality_agent.tools import PlatformClient

WAREHOUSE_FILENAME = "warehouse.sqlite3"


class PipelineService:
    """Used by the CLI and the UI, so every run is persisted the same way."""

    def __init__(
        self, database_path: str | Path = DEFAULT_DATABASE, warehouse_path: str | Path | None = None,
    ) -> None:
        self.database = Database(database_path)
        self.runs = RunRepository(self.database)
        self.incidents = IncidentRepository(self.database)
        # By default the warehouse sits next to the control database (runs/warehouse.sqlite3).
        if warehouse_path is None:
            warehouse_path = self.database.path.parent / WAREHOUSE_FILENAME
        self.simulator = PipelineSimulator(warehouse_path=warehouse_path)

    def run(
        self,
        scenario: Scenario | str | Path,
        *,
        input_path: str | Path | None = None,
        on_event: EventListener | None = None,
        agent_model: Model | str | None = None,
    ) -> PipelineRun:
        if isinstance(scenario, (str, Path)):
            scenario = load_scenario(scenario)
        pipeline = load_pipeline(scenario.pipeline_id)
        result = self._run(scenario, pipeline, input_path=input_path, on_event=on_event)
        if result.incident is not None:
            self.incidents.register(result.run_id)
            if agent_model is not None:
                self.analyze(result.run_id, agent_model, on_event=on_event)
                return self._stored_run(result.run_id)
        return result

    def _stored_run(self, run_id: str) -> PipelineRun:
        result = self.runs.get_run(run_id)
        if result is None:
            raise ValueError(f"A execução '{run_id}' não está concluída.")
        return result

    def _run(
        self, scenario: Scenario, pipeline: PipelineDefinition, *,
        input_path: str | Path | None = None,
        input_records: list[dict[str, Any]] | None = None,
        on_event: EventListener | None = None,
        incident_id: str | None = None, reason: str = "",
        destination_path: str | Path | None = None,
    ) -> PipelineRun:
        simulator = self.simulator if destination_path is None else PipelineSimulator(destination_path)
        version = self.runs.register_pipeline(pipeline)
        started: list[str] = []

        def persist(event: PipelineEvent) -> None:
            # Events are written as they happen, so other processes can follow a run in progress.
            if not started:
                self.runs.start_run(
                    run_id=event.run_id,
                    pipeline_id=pipeline.pipeline_id,
                    pipeline_version=version,
                    scenario_id=scenario.scenario_id,
                    seed=scenario.seed,
                    destination=str(simulator.destination.path.resolve()),
                    started_at=event.timestamp,
                )
                if incident_id is not None:
                    self.incidents.add_attempt(incident_id, event.run_id, reason)
                started.append(event.run_id)
            self.runs.append_event(event)
            if on_event is not None:
                on_event(event)

        try:
            result = simulator.run(
                scenario, input_path=input_path, input_records=input_records,
                pipeline_definition=pipeline, on_event=persist,
            )
        except (OSError, ValueError) as error:
            if started:
                self.runs.fail_run(started[0], str(error))
            raise
        self.runs.finish_run(result)
        return result

    def correct(
        self, run_id: str, payload: str, reason: str, *,
        agent_model: Model | str | None = None, on_event: EventListener | None = None,
    ) -> PipelineRun:
        if not reason.strip():
            raise ValueError("Indica o motivo da correção.")
        records = parse_corrected_batch(payload)
        incident = self.incidents.get_for_run(run_id)
        if incident is None:
            raise ValueError("Esta execução não pertence a um incidente.")
        if run_id != incident.latest_run_id:
            raise ValueError("Submete a correção para a tentativa mais recente do incidente.")
        latest = self._stored_run(incident.latest_run_id)
        if latest.pipeline_status == PipelineStatus.SUCCEEDED:
            raise ValueError("O último lote já foi carregado. Verifica-o sem criar outra entrega.")
        original = self._stored_run(incident.incident_id)
        summary = self.runs.get_summary(original.run_id)
        if summary is None:
            raise ValueError("A execução original não foi encontrada.")
        pipeline = self.runs.get_pipeline(original.pipeline_id, summary.pipeline_version)
        if pipeline is None:
            raise ValueError("A definição original da pipeline não foi encontrada.")
        scenario = Scenario(
            scenario_id=original.scenario_id, pipeline_id=original.pipeline_id, seed=original.seed,
            description="User-submitted correction of an existing incident.", faults=[],
        )
        self.incidents.claim_correction(incident)
        try:
            result = self._run(
                scenario, pipeline, input_records=records, on_event=on_event,
                incident_id=incident.incident_id, reason=reason.strip(), destination_path=original.destination,
            )
            status: IncidentState = (
                "resolved"
                if result.pipeline_status == PipelineStatus.SUCCEEDED and agent_model is None
                else "awaiting_correction"
            )
            self.incidents.set_status(incident.incident_id, status, run_id=result.run_id)
            if agent_model is not None:
                self.analyze(result.run_id, agent_model, on_event=on_event)
                return self._stored_run(result.run_id)
            return result
        except Exception:
            self.incidents.release_correction(incident.incident_id)
            raise

    def analyze(
        self, run_id: str, model: Model | str, *, on_event: EventListener | None = None,
    ) -> OrchestrationResult:
        incident = self.incidents.get_for_run(run_id)
        if incident is None or incident.latest_run_id != run_id:
            raise ValueError("A análise deve usar a tentativa mais recente do incidente.")
        if incident.status == "resolved":
            raise ValueError("Este incidente já foi resolvido.")
        result = self._stored_run(run_id)
        session_id = str(uuid4())
        self.incidents.start_session(session_id, run_id)

        def emit(kind: EventKind, message: str, status: StageStatus | None = None) -> None:
            event = PipelineEvent(
                run_id=run_id, sequence=len(result.events), timestamp=datetime.now(timezone.utc),
                kind=kind, stage=StageName.AGENT_INTERVENTION, status=status, message=message,
                level=LogLevel.ERROR if status == StageStatus.FAILED else LogLevel.INFO,
            )
            result.events.append(event)
            self.runs.append_event(event)
            if on_event is not None:
                on_event(event)

        def step(agent: str, kind: str, message: str) -> None:
            self.incidents.append_step(session_id, agent, kind, message)
            emit(EventKind.LOG, f"{agent}: {kind}" + (f" — {message}" if kind == "tool" else ""))

        async def investigate() -> OrchestrationResult:
            async with PlatformClient() as platform:
                return await AgentTeam(model, self.runs, platform, run_id, step).run(incident.incident_id)

        emit(EventKind.STAGE_STARTED, "Started agent investigation.")
        try:
            outcome = asyncio.run(investigate())
        except Exception as error:
            detail = f"{type(error).__name__}: {error}"
            self.incidents.append_step(session_id, "orchestrator", "error", detail)
            self.incidents.finish_session(session_id, error=detail)
            self.incidents.set_status(incident.incident_id, "analysis_failed", run_id=run_id)
            for stage in result.stages:
                if stage.name == StageName.AGENT_INTERVENTION:
                    stage.status = StageStatus.FAILED
            emit(EventKind.STAGE_FINISHED, f"Agent investigation failed: {detail}", StageStatus.FAILED)
            self.runs.finish_run(result)
            raise AgentExecutionError(run_id, f"A investigação dos agentes falhou: {detail}") from error
        status = StageStatus.PENDING if outcome.status == "awaiting_correction" else StageStatus.SUCCEEDED
        for stage in result.stages:
            if stage.name == StageName.AGENT_INTERVENTION:
                stage.status = status
        emit(EventKind.STAGE_FINISHED, f"Agent investigation: {outcome.status}.", status)
        self.incidents.finish_session(session_id, outcome=outcome)
        self.incidents.set_status(incident.incident_id, outcome.status, run_id=run_id)
        self.runs.finish_run(result)
        return outcome
