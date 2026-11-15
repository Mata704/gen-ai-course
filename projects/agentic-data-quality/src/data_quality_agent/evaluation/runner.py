"""Run deterministic scenario checks and, optionally, evaluate agent trajectories."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Iterable
from uuid import uuid4

from pydantic_ai.models import Model

from data_quality_agent.evaluation.models import (
    AgentExpectation,
    EvaluationCase,
    EvaluationCaseResult,
    EvaluationCheck,
    EvaluationReport,
)
from data_quality_agent.harness.team import AgentExecutionError
from data_quality_agent.persistence.models import IncidentWorkflow
from data_quality_agent.persistence.telemetry import TelemetryRepository
from data_quality_agent.service import PipelineService
from data_quality_agent.simulator.engine import SCENARIOS_DIR, load_scenario


def load_cases() -> list[EvaluationCase]:
    resource = files("data_quality_agent.evaluation").joinpath("cases.json")
    data = json.loads(resource.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported evaluation-case schema version.")
    cases = [EvaluationCase.model_validate(item) for item in data["cases"]]
    scenario_ids = [case.scenario_id for case in cases]
    if len(set(scenario_ids)) != len(scenario_ids):
        raise ValueError("Evaluation scenario IDs must be unique.")
    for case in cases:
        scenario_file = (SCENARIOS_DIR / case.scenario_file).resolve()
        if scenario_file.parent != SCENARIOS_DIR.resolve() or not scenario_file.is_file():
            raise ValueError(f"Scenario file for '{case.scenario_id}' is missing or outside the scenario directory.")
        if load_scenario(scenario_file).scenario_id != case.scenario_id:
            raise ValueError(f"Scenario file does not match evaluation ID '{case.scenario_id}'.")
    return cases


def evaluate_cases(
    *,
    with_agents: bool = False,
    model: Model | str | None = None,
    scenario_ids: Iterable[str] | None = None,
    workdir: str | Path | None = None,
) -> EvaluationReport:
    if with_agents and model is None:
        raise ValueError("An agent model is required when agent evaluation is enabled.")

    cases = load_cases()
    if scenario_ids is not None:
        selected_ids = set(scenario_ids)
        known_ids = {case.scenario_id for case in cases}
        unknown_ids = selected_ids - known_ids
        if unknown_ids:
            raise ValueError(f"Unknown evaluation scenario(s): {', '.join(sorted(unknown_ids))}.")
        cases = [case for case in cases if case.scenario_id in selected_ids]
    if not cases:
        raise ValueError("Select at least one evaluation scenario.")

    started_at = datetime.now(timezone.utc)
    if workdir is None:
        with TemporaryDirectory(prefix="data-quality-eval-") as temporary:
            results = _evaluate(cases, Path(temporary), with_agents=with_agents, model=model, retain=False)
    else:
        root = Path(workdir) / f"evaluation-{uuid4().hex}"
        root.mkdir(parents=True, exist_ok=False)
        results = _evaluate(cases, root, with_agents=with_agents, model=model, retain=True)
    return EvaluationReport(
        mode="agents" if with_agents else "deterministic",
        model_name=model if isinstance(model, str) else model.model_name if model is not None else None,
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        passed_cases=sum(result.passed for result in results),
        failed_cases=sum(not result.passed for result in results),
        results=results,
    )


def _evaluate(
    cases: list[EvaluationCase],
    workdir: Path,
    *,
    with_agents: bool,
    model: Model | str | None,
    retain: bool,
) -> list[EvaluationCaseResult]:
    results = []
    for case in cases:
        started = perf_counter()
        service = PipelineService(
            workdir / case.scenario_id / "control.sqlite3",
            warehouse_path=workdir / case.scenario_id / "warehouse.sqlite3",
        )
        scenario_path = SCENARIOS_DIR / case.scenario_file
        control_database = str(service.database.path.resolve()) if retain else None
        error_type = None
        try:
            run = service.run(scenario_path, agent_model=model if with_agents and case.agent else None)
            run_id = run.run_id
        except AgentExecutionError as error:
            error_type = type(error).__name__
            run_id = error.run_id
            run = service.runs.get_run(run_id)
        except (OSError, ValueError) as error:
            checks = [EvaluationCheck(
                name="execution", passed=False, expected="run completed", actual=type(error).__name__,
            )]
            results.append(EvaluationCaseResult(
                scenario_id=case.scenario_id, passed=False, run_id=None, checks=checks,
                error_type=type(error).__name__,
                duration_ms=(perf_counter() - started) * 1000, control_database=control_database,
                model_calls=TelemetryRepository(service.database).list_calls(),
            ))
            continue

        if run is None:
            checks = [EvaluationCheck(
                name="execution", passed=False, expected="persisted run", actual="missing",
            )]
            results.append(EvaluationCaseResult(
                scenario_id=case.scenario_id, passed=False, run_id=run_id, checks=checks,
                error_type=error_type,
                duration_ms=(perf_counter() - started) * 1000, control_database=control_database,
                model_calls=TelemetryRepository(service.database).list_calls(),
            ))
            continue

        checks = [
            EvaluationCheck(
                name="pipeline_status", passed=run.pipeline_status == case.pipeline_status,
                expected=case.pipeline_status.value, actual=run.pipeline_status.value,
            ),
            EvaluationCheck(
                name="quality_status", passed=run.quality_status == case.quality_status,
                expected=case.quality_status.value, actual=run.quality_status.value,
            ),
            EvaluationCheck(
                name="required_findings",
                passed=set(case.required_findings) <= {finding.rule_id for finding in run.findings},
                expected=case.required_findings,
                actual=sorted({finding.rule_id for finding in run.findings}),
            ),
        ]
        workflow = service.incidents.get_for_run(run_id)
        latest_run_id = workflow.latest_run_id if workflow is not None else run_id
        output_count = len(service.runs.get_output(latest_run_id))
        expected_output_count = (
            case.agent.output_count if with_agents and case.agent is not None else case.output_count
        )
        checks.append(EvaluationCheck(
            name="delivered_records", passed=output_count == expected_output_count,
            expected=expected_output_count, actual=output_count,
        ))

        if with_agents and case.agent is not None:
            checks.extend(_agent_checks(service, workflow, run_id, case.agent, error_type))
        case_passed = all(check.passed for check in checks)
        results.append(EvaluationCaseResult(
            scenario_id=case.scenario_id, passed=case_passed, run_id=run_id,
            checks=checks, error_type=error_type,
            duration_ms=(perf_counter() - started) * 1000, control_database=control_database,
            model_calls=TelemetryRepository(service.database).list_calls(),
        ))
    return results


def _agent_checks(
    service: PipelineService,
    workflow: IncidentWorkflow | None,
    run_id: str,
    expected: AgentExpectation,
    error_type: str | None,
) -> list[EvaluationCheck]:
    if workflow is None:
        actual_status = None
        actions = []
    else:
        actual_status = workflow.status
        actions = service.actions.list_actions(workflow.incident_id)
    checks = [
        EvaluationCheck(
            name="agent_execution", passed=error_type is None,
            expected="completed", actual=error_type or "completed",
        ),
        EvaluationCheck(
            name="incident_status", passed=actual_status == expected.incident_status,
            expected=expected.incident_status, actual=actual_status,
        ),
    ]
    actual_actions = [{"action": action.action, "status": action.status} for action in actions]
    expected_actions = (
        [{"action": expected.expected_action, "status": "executed"}]
        if expected.expected_action is not None else []
    )
    checks.append(EvaluationCheck(
        name="action_trace", passed=actual_actions == expected_actions,
        expected=expected_actions, actual=actual_actions,
    ))
    sessions = service.incidents.list_sessions(run_id)
    actual_roles = sorted({
        step.agent
        for session in sessions
        for step in service.incidents.list_steps(session.session_id)
    })
    checks.append(EvaluationCheck(
        name="required_agent_roles", passed=set(expected.required_roles) <= set(actual_roles),
        expected=expected.required_roles, actual=actual_roles,
    ))
    return checks
