"""Application service: run a pipeline, keep its history in the control database and deliver
approved data to the separate destination (warehouse) file."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic_ai.models import Model

from data_quality_agent.harness.orchestrator import OrchestrationResult
from data_quality_agent.harness.policies import PolicyDenied, check_retry, plan_quarantine
from data_quality_agent.harness.team import AgentExecutionError, AgentTeam
from data_quality_agent.corrections import parse_corrected_batch
from data_quality_agent.persistence.actions import ActionRepository
from data_quality_agent.persistence.approvals import ApprovalRepository
from data_quality_agent.persistence.database import DEFAULT_DATABASE, Database
from data_quality_agent.persistence.incidents import IncidentRepository
from data_quality_agent.persistence.models import ActionName, IncidentState, IncidentWorkflow
from data_quality_agent.persistence.rule_changes import RuleChangeRepository
from data_quality_agent.persistence.repository import RunRepository
from data_quality_agent.simulator.engine import (
    SCENARIOS_DIR,
    EventListener,
    PipelineSimulator,
    load_pipeline,
    load_scenario,
)
from data_quality_agent.simulator.destination import SQLiteDestination
from data_quality_agent.simulator.models import (
    EventKind, FaultKind, LogLevel, PipelineDefinition, PipelineEvent, PipelineRun, PipelineStatus,
    Scenario, StageName, StageStatus,
)
from data_quality_agent.tools import PlatformClient
from data_quality_agent.tools.platform_client import RemoteToolError

WAREHOUSE_FILENAME = "warehouse.sqlite3"


class PipelineService:
    """Used by the CLI and the UI, so every run is persisted the same way."""

    def __init__(
        self, database_path: str | Path = DEFAULT_DATABASE, warehouse_path: str | Path | None = None,
    ) -> None:
        self.database = Database(database_path)
        self.runs = RunRepository(self.database)
        self.incidents = IncidentRepository(self.database)
        self.actions = ActionRepository(self.database)
        self.approvals = ApprovalRepository(self.database)
        self.rule_changes = RuleChangeRepository(self.database)
        # By default the warehouse sits next to the control database (runs/warehouse.sqlite3).
        if warehouse_path is None:
            warehouse_path = self.database.path.parent / WAREHOUSE_FILENAME
        self.simulator = PipelineSimulator(warehouse_path=warehouse_path)

    def clean(self) -> None:
        """Reset this workspace, including retained evaluations, but never its source data."""
        evaluation_root = self.database.path.resolve().parent / "evaluations"
        case_databases: list[tuple[Path, Path]] = []
        if evaluation_root.is_symlink():
            raise ValueError("A pasta de avaliações não pode ser uma ligação simbólica.")
        for evaluation in sorted(evaluation_root.glob("evaluation-*")):
            if evaluation.is_symlink():
                raise ValueError(f"A avaliação não pode ser uma ligação simbólica: {evaluation}")
            if not evaluation.is_dir():
                continue
            for case in sorted(evaluation.iterdir()):
                if case.is_symlink():
                    raise ValueError(f"O caso não pode ser uma ligação simbólica: {case}")
                if case.is_dir():
                    case_databases.append((case / "control.sqlite3", case / WAREHOUSE_FILENAME))
        paths = [
            self.database.path, self.simulator.destination.path,
            *(path for pair in case_databases for path in pair),
        ]
        for path in paths:
            if path.is_symlink():
                raise ValueError(f"A base a limpar não pode ser uma ligação simbólica: {path}")
        # Keep the main history until all destinations and case databases have been cleared.
        for control, warehouse in case_databases:
            SQLiteDestination(warehouse).clear()
            if control.is_file():
                Database(control).clear()
        self.simulator.destination.clear()
        self.database.clear()

    def run(
        self,
        scenario: Scenario | str | Path,
        *,
        input_path: str | Path | None = None,
        input_records: list[dict[str, Any]] | None = None,
        on_event: EventListener | None = None,
        agent_model: Model | str | None = None,
    ) -> PipelineRun:
        if isinstance(scenario, (str, Path)):
            scenario = load_scenario(scenario)
        pipeline = self.current_pipeline(scenario.pipeline_id)
        result = self._run(
            scenario, pipeline, input_path=input_path, input_records=input_records, on_event=on_event,
        )
        if result.incident is not None:
            self.incidents.register(result.run_id)
            if agent_model is not None:
                self.analyze(result.run_id, agent_model, on_event=on_event)
                return self._stored_run(result.run_id)
        return result

    def current_pipeline(self, pipeline_id: str) -> PipelineDefinition:
        """Bundled definition plus currently approved, bounded rule overrides."""
        return self.rule_changes.apply_overrides(load_pipeline(pipeline_id))

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
        run_id: str | None = None,
    ) -> PipelineRun:
        simulator = self.simulator if destination_path is None else PipelineSimulator(destination_path)
        if run_id is not None and self.runs.reset_interrupted_run(run_id):
            simulator.destination.delete_run(run_id)
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
                scenario, run_id=run_id, input_path=input_path, input_records=input_records,
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

    # Automatic actions (asked by the remediation agent, allowed by harness/policies.py) ----------

    def source_system(self, run_id: str) -> str | None:
        pipeline = self._stored_pipeline(run_id)
        return pipeline.source_system if pipeline else None

    def retry_ingestion(self, run_id: str, *, requested_by: str, source_status: str | None) -> dict[str, Any]:
        incident, run, pipeline = self._action_context(run_id)
        check_retry(
            incident_kind=run.incident.kind if run.incident else None, run=run, pipeline=pipeline,
            retries_done=self.actions.count_executed(incident.incident_id, "retry_ingestion"),
            source_status=source_status,
        )
        bundled = self._bundled_scenario(run.scenario_id)
        if bundled is None:
            raise PolicyDenied(f"The source of scenario '{run.scenario_id}' is not known; it cannot be read again.")
        # The source is read again; the failure that stopped the previous attempt is not injected again.
        scenario = bundled.model_copy(update={"faults": [
            fault for fault in bundled.faults
            if fault.kind not in (FaultKind.SOURCE_UNAVAILABLE, FaultKind.PIPELINE_FAILURE)
        ]})
        return self._action_attempt(
            incident.incident_id, run, pipeline, scenario, "retry_ingestion", requested_by,
            detail=f"Ingestão repetida: a plataforma reporta a origem como '{source_status}'.",
            request={"source_status": source_status},
        )

    def quarantine_failed_records(self, run_id: str, *, requested_by: str) -> dict[str, Any]:
        incident, run, pipeline = self._action_context(run_id)
        held = plan_quarantine(run=run, pipeline=pipeline)
        remaining = [record for index, record in enumerate(run.input_records) if index not in held]
        # Data faults are already in the ingested records; only the scenario's delay still applies.
        bundled = self._bundled_scenario(run.scenario_id)
        scenario = Scenario(
            scenario_id=run.scenario_id, pipeline_id=run.pipeline_id, seed=run.seed,
            description="Automatic quarantine of the records that failed row-level rules.",
            faults=[fault for fault in (bundled.faults if bundled else []) if fault.kind == FaultKind.DELAY],
        )
        return self._action_attempt(
            incident.incident_id, run, pipeline, scenario, "quarantine_failed_records", requested_by,
            input_records=remaining,
            quarantined={index: (rules, run.input_records[index]) for index, rules in held.items()},
            detail=f"{len(held)} de {len(run.input_records)} registos retidos em quarentena.",
        )

    def _stored_pipeline(self, run_id: str) -> PipelineDefinition | None:
        summary = self.runs.get_summary(run_id)
        return self.runs.get_pipeline(summary.pipeline_id, summary.pipeline_version) if summary else None

    def _action_context(self, run_id: str) -> tuple[IncidentWorkflow, PipelineRun, PipelineDefinition]:
        incident = self.incidents.get_for_run(run_id)
        if incident is None:
            raise PolicyDenied("This run does not belong to an incident.")
        if incident.latest_run_id != run_id:
            raise PolicyDenied(f"Act only on the latest attempt of the incident ({incident.latest_run_id}).")
        if incident.status != "investigating":
            raise PolicyDenied("Automatic actions run only during an agent investigation.")
        run = self._stored_run(run_id)
        pipeline = self._stored_pipeline(run_id)
        if pipeline is None:
            raise PolicyDenied("The pipeline definition of this run was not found.")
        return incident, run, pipeline

    @staticmethod
    def _bundled_scenario(scenario_id: str) -> Scenario | None:
        for path in sorted(SCENARIOS_DIR.glob("*.json")):
            scenario = load_scenario(path)
            if scenario.scenario_id == scenario_id:
                return scenario
        return None

    def _action_attempt(
        self, incident_id: str, run: PipelineRun, pipeline: PipelineDefinition, scenario: Scenario,
        action: ActionName, requested_by: str, *, detail: str,
        input_records: list[dict[str, Any]] | None = None,
        quarantined: dict[int, tuple[list[str], dict[str, Any]]] | None = None,
        request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        action_id = self.actions.claim(
            incident_id, run.run_id, action, requested_by, request=request,
        )
        return self._execute_claimed_action(
            action_id, incident_id, run, pipeline, scenario, action, requested_by, detail,
            input_records=input_records, quarantined=quarantined,
        )

    def _execute_claimed_action(
        self, action_id: int, incident_id: str, run: PipelineRun,
        pipeline: PipelineDefinition, scenario: Scenario,
        action: ActionName, requested_by: str, detail: str, *,
        input_records: list[dict[str, Any]] | None = None,
        quarantined: dict[int, tuple[list[str], dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        result = self._run(
            scenario, pipeline, input_records=input_records, incident_id=incident_id,
            reason=f"Ação automática '{action}' pedida pelo agente {requested_by}.",
            destination_path=run.destination,
            run_id=self.actions.execution_run_id(action_id),
        )
        self.actions.complete(action_id, result_run_id=result.run_id, detail=detail, quarantined=quarantined)
        return {
            "ref": f"action:{action_id}",
            "action": action,
            "status": "executed",
            "previous_run_id": run.run_id,
            "new_run_id": result.run_id,
            "pipeline_status": result.pipeline_status.value,
            "quality_status": result.quality_status.value,
            "failed_rules": [finding.rule_id for finding in result.findings],
            "records_delivered": len(result.output_records),
            "records_quarantined": len(quarantined or {}),
            "detail": detail,
        }

    def recover_interrupted_actions(self, incident_id: str) -> list[dict[str, Any]]:
        """Resume claimed actions by replaying the same deterministic run id or finalizing its outcome."""
        self.incidents.recover_stale_sessions(
            incident_id, stale_before=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        if self.incidents.has_active_session(incident_id):
            raise PolicyDenied("An agent investigation is still active; wait before resuming the action.")
        recovered: list[dict[str, Any]] = []
        for action in self.actions.list_interrupted(incident_id):
            source = self._stored_run(action.source_run_id)
            pipeline = self._stored_pipeline(source.run_id)
            if pipeline is None:
                raise PolicyDenied("The pipeline definition of an interrupted action was not found.")
            execution_run_id = action.execution_run_id
            if execution_run_id is None:
                prior_attempt = self.incidents.find_action_attempt(
                    incident_id, action.action, action.requested_by,
                )
                execution_run_id = self.actions.ensure_execution_run_id(action.action_id, prior_attempt)
            summary = self.runs.get_summary(execution_run_id)
            outcome_persisted = summary is not None and summary.status in ("succeeded", "blocked")
            quarantined = None
            detail = "Ação retomada com a mesma chave idempotente."
            if action.action == "quarantine_failed_records":
                held = plan_quarantine(run=source, pipeline=pipeline)
                quarantined = {
                    index: (rules, source.input_records[index]) for index, rules in held.items()
                }
                remaining = [
                    record for index, record in enumerate(source.input_records) if index not in held
                ]
                bundled = self._bundled_scenario(source.scenario_id)
                scenario = Scenario(
                    scenario_id=source.scenario_id, pipeline_id=source.pipeline_id, seed=source.seed,
                    description="Resumed quarantine action.",
                    faults=[fault for fault in (bundled.faults if bundled else []) if fault.kind == FaultKind.DELAY],
                )
                input_records = remaining
                detail = f"{len(held)} de {len(source.input_records)} registos retidos em quarentena."
            else:
                if outcome_persisted:
                    scenario = None
                    input_records = None
                    detail = "Resultado já persistido; ação retomada sem repetir a entrega."
                else:
                    source_status = self._current_source_status(source.run_id)
                    check_retry(
                        incident_kind=source.incident.kind if source.incident else None,
                        run=source, pipeline=pipeline,
                        retries_done=self.actions.count_executed(incident_id, "retry_ingestion"),
                        source_status=source_status,
                    )
                    bundled = self._bundled_scenario(source.scenario_id)
                    if bundled is None:
                        raise PolicyDenied(f"The source of scenario '{source.scenario_id}' is not known.")
                    scenario = bundled.model_copy(update={"faults": [
                        fault for fault in bundled.faults
                        if fault.kind not in (FaultKind.SOURCE_UNAVAILABLE, FaultKind.PIPELINE_FAILURE)
                    ]})
                    input_records = None
                    detail = f"Retry retomado; a origem reporta '{source_status}'."

            if outcome_persisted:
                result = self._stored_run(execution_run_id)
            else:
                if scenario is None:
                    raise RuntimeError("The interrupted action could not be reconstructed.")
                result = self._run(
                    scenario, pipeline, input_records=input_records, incident_id=incident_id,
                    reason=f"Ação automática '{action.action}' retomada.",
                    destination_path=source.destination, run_id=execution_run_id,
                )
            self.actions.complete(
                action.action_id, result_run_id=result.run_id, detail=detail, quarantined=quarantined,
            )
            recovered.append({
                "action_id": action.action_id, "run_id": result.run_id,
                "pipeline_status": result.pipeline_status.value,
            })
        if recovered:
            workflow = self.incidents.get_for_run(recovered[-1]["run_id"])
            if workflow is not None and workflow.status == "investigating":
                self.incidents.set_status(
                    incident_id, "analysis_failed", run_id=workflow.latest_run_id,
                )
        return recovered

    def _current_source_status(self, run_id: str) -> str | None:
        system = self.source_system(run_id)
        if system is None:
            return None

        async def read_status() -> str | None:
            async with PlatformClient() as platform:
                if "get_source_status" not in platform.pinned:
                    return None
                try:
                    return (await platform.call("get_source_status", {"system_id": system})).get("status")
                except RemoteToolError:
                    return None

        return asyncio.run(read_status())

    def recover_stale_investigation(self, incident_id: str) -> None:
        """Mark an abandoned agent session failed so a fresh session can continue from its checkpoint."""
        recovered = self.incidents.recover_stale_sessions(
            incident_id, stale_before=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        if not recovered:
            raise PolicyDenied("No agent investigation is stale enough to resume; wait at least 10 minutes.")

    def analyze(
        self, run_id: str, model: Model | str, *, on_event: EventListener | None = None,
    ) -> OrchestrationResult:
        incident = self.incidents.get_for_run(run_id)
        if incident is None or incident.latest_run_id != run_id:
            raise ValueError("A análise deve usar a tentativa mais recente do incidente.")
        if incident.status == "resolved":
            raise ValueError("Este incidente já foi resolvido.")
        result = self._stored_run(run_id)
        resume_context = self._investigation_checkpoint(incident.incident_id)
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
            emit(EventKind.LOG, f"{agent}: {kind}" + (f" — {message}" if kind in ("tool", "action") else ""))

        async def investigate() -> tuple[OrchestrationResult, str]:
            async with PlatformClient() as platform:
                team = AgentTeam(
                    model, self.runs, platform, run_id, step, executor=self, session_id=session_id,
                )
                outcome = await team.run(incident.incident_id, resume_context=resume_context)
                return outcome, team.run_id

        emit(EventKind.STAGE_STARTED, "Started agent investigation.")
        try:
            outcome, latest_run_id = asyncio.run(investigate())
        except Exception as error:
            detail = f"{type(error).__name__}: {error}"
            self.incidents.append_step(session_id, "orchestrator", "error", detail)
            self.incidents.finish_session(session_id, error=detail)
            # An action may have created a newer attempt before the failure.
            latest = self.incidents.get_for_run(run_id)
            self.incidents.set_status(
                incident.incident_id, "analysis_failed", run_id=latest.latest_run_id if latest else run_id,
            )
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
        self.incidents.set_status(incident.incident_id, outcome.status, run_id=latest_run_id)
        self.runs.finish_run(result)
        return outcome

    def _investigation_checkpoint(self, incident_id: str, *, limit: int = 4000) -> str:
        attempts = self.incidents.list_attempts(incident_id)
        sessions = [
            session
            for attempt in attempts
            for session in self.incidents.list_sessions(attempt.run_id)
            if session.status != "running"
        ]
        lines: list[str] = []
        for session in sessions[-3:]:
            for step in self.incidents.list_steps(session.session_id):
                if step.kind in {"completed", "action", "error"}:
                    lines.append(f"{step.agent}/{step.kind}: {step.message}")
        return "\n".join(lines)[-limit:]
