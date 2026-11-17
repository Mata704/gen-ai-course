import asyncio
import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai import ModelRetry
from pydantic_ai.usage import RequestUsage

from data_quality_agent.evaluation import evaluate_cases
from data_quality_agent.harness.specialists import Observed
from data_quality_agent.harness.team import AgentExecutionError, AgentTeam
from data_quality_agent.mcp.server import build_server
from data_quality_agent.persistence.audit import AuditRepository
from data_quality_agent.persistence.telemetry import TelemetryRepository
from data_quality_agent.service import PipelineService
from data_quality_agent.simulator.engine import SCENARIOS_DIR, DATASETS_DIR
from data_quality_agent.tools import PlatformClient


def content(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, str):
        return json.loads(value)
    if not isinstance(value, dict):
        raise AssertionError(f"Unexpected tool return: {value!r}")
    return value


def scripted_model(
    *, false_resolution: bool = False, action: str | None = None, seen: list[str] | None = None,
    follow_up: bool = False,
) -> FunctionModel:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if seen is not None:
            seen.extend(
                str(part.content) for message in messages if isinstance(message, ModelRequest)
                for part in message.parts if isinstance(part, ToolReturnPart)
            )
        names = {tool.name for tool in info.function_tools}
        if "get_dataset_contract" in names:
            contract = next(tool for tool in info.function_tools if tool.name == "get_dataset_contract")
            assert "Data contract published" in contract.description
            assert "dataset_id" in contract.parameters_json_schema["properties"]
        returned = {
            part.tool_name: content(part.content)
            for message in messages if isinstance(message, ModelRequest)
            for part in message.parts if isinstance(part, ToolReturnPart) and part.tool_name in names
        }
        prompt = next(
            part.content for message in messages if isinstance(message, ModelRequest)
            for part in message.parts if isinstance(part, UserPromptPart)
        )
        assert isinstance(prompt, str)
        match = re.search(r"Current attempt(?: run_id)?: ([\w-]+)", prompt)
        assert match
        run_id = match.group(1)
        output_name = info.output_tools[0].name
        if "ask_investigation" in names:
            if "ask_investigation" not in returned:
                return ModelResponse(parts=[ToolCallPart(
                    "ask_investigation", {"task": "Read the findings, logs and source contract."},
                )])
            if returned.get("ask_remediation", {}).get("decision") == "needs_evidence":
                if returned["ask_investigation"]["summary"] != "Source availability checked.":
                    return ModelResponse(parts=[ToolCallPart(
                        "ask_investigation", {"task": "Check current source availability."},
                    )])
                return ModelResponse(parts=[ToolCallPart(
                    "ask_remediation", {"task": "Use the newly checked source availability."},
                )])
            if "ask_remediation" not in returned:
                return ModelResponse(parts=[ToolCallPart("ask_remediation", {"task": json.dumps(returned)})])
            actions = returned.get("ask_remediation", {}).get("actions_taken", [])
            return ModelResponse(parts=[ToolCallPart(output_name, {
                "status": "resolved" if false_resolution else "awaiting_correction",
                "summary": "Action result returned." if actions else "A corrected batch is needed.",
                "probable_cause": "Invalid source records.",
                "evidence_refs": [ref for report in returned.values() for ref in report["evidence_refs"]],
                "actions_taken": actions,
                "next_step": "Check action result." if actions else "Submit corrected JSON.",
            })])

        if "get_batch_profile" in names:
            role, calls = "investigation", [
                ("get_quality_findings", {"run_id": run_id}),
                ("get_run_logs", {"run_id": run_id}),
                ("get_dataset_contract", {"dataset_id": "sales.orders"}),
            ]
            if "Task: Check current source availability." in prompt:
                calls = [("get_source_status", {"system_id": "orders-export-api"})]
        else:
            role, calls = "remediation", [("get_incident", {"run_id": run_id})]
            needs_evidence = follow_up and "Source availability checked." not in prompt
            if action is not None and "get_incident" in returned and not needs_evidence:
                calls.append((action, {"run_id": run_id}))
        missing = [(name, args) for name, args in calls if name not in returned]
        if missing:
            return ModelResponse(parts=[ToolCallPart(name, args) for name, args in missing])
        requesting = role == "remediation" and follow_up and "Source availability checked." not in prompt
        return ModelResponse(parts=[ToolCallPart(output_name, {
            "role": role, "summary": (
                "Source availability checked." if "get_source_status" in returned else "Observed results from tools."
            ),
            "evidence_refs": [value["tool_ref"] for value in returned.values() if "tool_ref" in value],
            "recommendation": "Submit a corrected batch.",
            "actions_taken": [
                value["ref"] for value in returned.values() if value.get("status") == "executed"
            ],
            "decision": (
                "complete" if role == "investigation" else "needs_evidence" if requesting else
                "action_executed" if any(v.get("status") == "executed" for v in returned.values())
                else "awaiting_correction"
            ),
            "missing_evidence": ["Current source availability"] if requesting else [],
            "follow_up_question": "Is the source currently available?" if requesting else None,
        })])

    return FunctionModel(respond)


def test_agents_delegate_and_code_verifies_the_same_incident(tmp_path: Path) -> None:
    service = PipelineService(tmp_path / "history.sqlite3")
    failed = service.run(SCENARIOS_DIR / "quality_issues.json", agent_model=scripted_model())
    workflow = service.incidents.get_for_run(failed.run_id)
    assert workflow.status == "awaiting_correction"
    session = service.incidents.list_sessions(failed.run_id)[0]
    assert session.status == "completed"
    assert {step.agent for step in service.incidents.list_steps(session.session_id)} == {
        "orchestrator", "investigation", "remediation", "verification",
    }
    calls = AuditRepository(service.database).list_calls(run_id=failed.run_id)
    assert any(call.tool == "get_dataset_contract" and call.source == "mcp" for call in calls)

    corrected = service.correct(
        failed.run_id, (DATASETS_DIR / "orders.json").read_text(encoding="utf-8"),
        "Lote corrigido pela origem.", agent_model=scripted_model(),
    )
    workflow = service.incidents.get_for_run(corrected.run_id)
    assert workflow.incident_id == failed.run_id
    assert workflow.status == "resolved"
    assert service.incidents.list_sessions(corrected.run_id)[0].outcome["status"] == "resolved"
    assert AuditRepository(service.database).list_calls(run_id=corrected.run_id) == []
    assert TelemetryRepository(service.database).list_calls(run_ids=[corrected.run_id]) == []


def test_model_cannot_resolve_an_unrecovered_incident(tmp_path: Path) -> None:
    service = PipelineService(tmp_path / "history.sqlite3")
    with pytest.raises(AgentExecutionError):
        service.run(SCENARIOS_DIR / "quality_issues.json", agent_model=scripted_model(false_resolution=True))
    [summary] = service.runs.list_runs()
    assert summary.status == "blocked"
    assert service.incidents.get_for_run(summary.run_id).status == "analysis_failed"
    session = service.incidents.list_sessions(summary.run_id)[0]
    assert session.status == "failed"
    assert "deterministic recovery verification failed" in session.error
    steps = service.incidents.list_steps(session.session_id)
    assert any(step.agent == "orchestrator" and step.kind == "completed" for step in steps)
    assert any(step.agent == "verification" and step.kind == "error" for step in steps)
    assert service.runs.get_output(summary.run_id) == []


def test_mcp_description_and_schema_reach_the_model_tool_definition(tmp_path: Path) -> None:
    service = PipelineService(tmp_path / "history.sqlite3")

    async def inspect_tools() -> None:
        async with PlatformClient(build_server()) as platform:
            team = AgentTeam(scripted_model(), service.runs, platform, "run-x", lambda *_: None)
            tools = team._bridge(team.gateways["investigation"], Observed())
            contract = next(tool for tool in tools if tool.name == "get_dataset_contract")
            announced = next(tool for tool in platform.listed if tool.name == contract.name)
            assert contract.description == announced.description
            assert contract.function_schema.json_schema == announced.input_schema
            assert "get_source_status" in {tool.name for tool in tools}

    asyncio.run(inspect_tools())


def test_fabricated_evidence_is_rejected_and_persisted(tmp_path: Path) -> None:
    def forged(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
            "status": "unresolved", "summary": "Unsupported.", "probable_cause": "Unknown.",
            "evidence_refs": ["tool:invented"], "next_step": "Stop.",
        })])

    service = PipelineService(tmp_path / "history.sqlite3")
    with pytest.raises(AgentExecutionError):
        service.run(SCENARIOS_DIR / "source_unavailable.json", agent_model=FunctionModel(forged))
    [summary] = service.runs.list_runs()
    assert service.incidents.list_sessions(summary.run_id)[0].status == "failed"
    assert service.incidents.get_for_run(summary.run_id).status == "analysis_failed"


def test_remediation_retries_and_code_confirms_despite_model_awaiting_correction(tmp_path: Path) -> None:
    service = PipelineService(tmp_path / "history.sqlite3")
    failed = service.run(SCENARIOS_DIR / "source_unavailable.json", agent_model=scripted_model(action="retry_ingestion"))
    workflow = service.incidents.get_for_run(failed.run_id)
    assert workflow.status == "resolved"
    [action] = service.actions.list_actions(failed.run_id)
    assert (action.action, action.status, action.result_run_id) == (
        "retry_ingestion", "executed", workflow.latest_run_id,
    )
    retried = service.runs.get_run(workflow.latest_run_id)
    assert retried.pipeline_status.value == "succeeded"
    assert len(retried.output_records) == 40
    outcome = service.incidents.list_sessions(failed.run_id)[0].outcome
    assert outcome["actions_taken"] == [f"action:{action.action_id}"]
    [session] = service.incidents.list_sessions(failed.run_id)
    completed = [
        step for step in service.incidents.list_steps(session.session_id) if step.kind == "completed"
    ]
    assert [step.agent for step in completed[-2:]] == ["orchestrator", "verification"]
    assert json.loads(completed[-2].message)["status"] == "awaiting_correction"
    assert json.loads(completed[-1].message) == {
        "run_id": workflow.latest_run_id,
        "proposed_status": "awaiting_correction",
        "confirmed_status": "resolved",
        "recovery_verified": True,
    }


def test_agent_evaluation_checks_the_retry_trajectory(tmp_path: Path) -> None:
    report = evaluate_cases(
        with_agents=True,
        model=scripted_model(action="retry_ingestion"),
        scenario_ids=["orders-source-unavailable"],
        workdir=tmp_path,
    )

    assert report.passed_cases == 1
    assert report.failed_cases == 0
    assert report.results[0].model_calls
    assert report.results[0].duration_ms > 0
    assert Path(report.results[0].control_database).is_file()


def test_team_records_each_request_once_across_action_attempts(tmp_path: Path) -> None:
    base = scripted_model(action="retry_ingestion")
    requests = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        assert base.function is not None
        response = base.function(messages, info)
        assert isinstance(response, ModelResponse)
        response.usage = RequestUsage(input_tokens=100, output_tokens=20)
        response.model_name = "scripted-usage"
        requests.append(response)
        return response

    service = PipelineService(tmp_path / "history.sqlite3")
    run = service.run(
        SCENARIOS_DIR / "source_unavailable.json", agent_model=FunctionModel(respond, model_name="scripted-usage"),
    )
    workflow = service.incidents.get_for_run(run.run_id)
    calls = TelemetryRepository(service.database).list_calls()

    assert len(calls) == len(requests)
    assert sum(call.input_tokens for call in calls) == len(requests) * 100
    assert sum(call.output_tokens for call in calls) == len(requests) * 20
    assert {call.model_name for call in calls} == {"scripted-usage"}
    assert {call.run_id for call in calls} == {run.run_id, workflow.latest_run_id}
    [session] = service.incidents.list_sessions(run.run_id)
    assert {call.session_id for call in calls} == {session.session_id}


def test_quarantine_delivers_the_rest_and_records_never_reach_the_agents(tmp_path: Path) -> None:
    service = PipelineService(tmp_path / "history.sqlite3")
    seen: list[str] = []
    blocked = service.run(
        SCENARIOS_DIR / "few_invalid_records.json",
        agent_model=scripted_model(action="quarantine_failed_records", seen=seen),
    )
    workflow = service.incidents.get_for_run(blocked.run_id)
    assert workflow.status == "resolved"
    delivered = service.runs.get_run(workflow.latest_run_id)
    assert len(delivered.output_records) == 38
    held = service.actions.list_failed_records(blocked.run_id)
    assert [(item.position, item.rule_ids, item.status) for item in held] == [
        (7, ["valid-amount"], "held"), (12, ["valid-status"], "held"),
    ]
    # Humans can review the held-back records; the agents only saw rules, counts and positions.
    assert seen and not any(re.search(r"ORD-\d", text) for text in seen)


def test_quarantine_is_denied_when_too_many_records_fail(tmp_path: Path) -> None:
    service = PipelineService(tmp_path / "history.sqlite3")
    blocked = service.run(
        SCENARIOS_DIR / "quality_issues.json", agent_model=scripted_model(action="quarantine_failed_records"),
    )
    assert service.incidents.get_for_run(blocked.run_id).status == "awaiting_correction"
    assert service.actions.list_actions(blocked.run_id) == []
    [call] = [
        call for call in AuditRepository(service.database).list_calls(run_id=blocked.run_id)
        if call.tool == "quarantine_failed_records"
    ]
    assert call.outcome == "blocked" and call.detail.startswith("Policy:")


def test_orchestrator_routes_missing_evidence_back_to_investigation(tmp_path: Path) -> None:
    service = PipelineService(tmp_path / "history.sqlite3")
    failed = service.run(
        SCENARIOS_DIR / "source_unavailable.json",
        agent_model=scripted_model(action="retry_ingestion", follow_up=True),
    )
    [session] = service.incidents.list_sessions(failed.run_id)
    reports = [
        json.loads(step.message) for step in service.incidents.list_steps(session.session_id)
        if step.kind == "completed" and step.agent in {"investigation", "remediation"}
    ]
    assert [r["decision"] for r in reports] == ["complete", "needs_evidence", "complete", "action_executed"]
    assert service.incidents.get_for_run(failed.run_id).status == "resolved"
    assert any(
        call.tool == "get_source_status" and call.agent == "investigation"
        for call in AuditRepository(service.database).list_calls(run_id=failed.run_id)
    )


def test_team_stops_repeated_tasks_and_queries_without_new_evidence(tmp_path: Path) -> None:
    service = PipelineService(tmp_path / "history.sqlite3")
    failed = service.run(SCENARIOS_DIR / "source_unavailable.json")

    async def investigate() -> None:
        async with PlatformClient(build_server()) as platform:
            team = AgentTeam(scripted_model(follow_up=True), service.runs, platform, failed.run_id, lambda *_: None)
            with pytest.raises(ModelRetry, match="investigation first"):
                await team.ask("remediation", "Try recovery before investigation.")
            await team.ask("investigation", "Initial diagnosis.")
            with pytest.raises(ModelRetry, match="Do not repeat"):
                await team.ask("investigation", "Initial diagnosis.")
            await team.ask("remediation", "Choose next step.")
            with pytest.raises(ModelRetry, match="investigation first"):
                await team.ask("remediation", "Try without the missing evidence.")
            await team.ask("investigation", "Recheck the original evidence.")
            await team.ask("remediation", "Reconsider with no new facts.")
            assert team.no_progress == 2
            with pytest.raises(ModelRetry, match="No new evidence"):
                await team.ask("investigation", "Another differently worded repetition.")

    asyncio.run(investigate())


def test_failed_quarantine_attempt_is_investigated_before_more_remediation(tmp_path: Path, monkeypatch) -> None:
    service = PipelineService(tmp_path / "history.sqlite3")
    pipeline = service.current_pipeline("orders_daily")
    pipeline = pipeline.model_copy(update={"rules": [
        rule.model_copy(update={"minimum_count": 39}) if rule.rule_id == "minimum-volume" else rule
        for rule in pipeline.rules
    ]})
    monkeypatch.setattr(service, "current_pipeline", lambda _: pipeline)
    base = scripted_model(action="quarantine_failed_records")

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        names = {tool.name for tool in info.function_tools}
        returns = [
            part for message in messages if isinstance(message, ModelRequest)
            for part in message.parts if isinstance(part, ToolReturnPart)
        ]
        remediations = [part for part in returns if part.tool_name == "ask_remediation"]
        investigations = [part for part in returns if part.tool_name == "ask_investigation"]
        action_results = [
            content(part.content) for part in returns if part.tool_name == "quarantine_failed_records"
        ]
        executed = next((value for value in action_results if value.get("status") == "executed"), None)
        if "quarantine_failed_records" in names and executed:
            if len(action_results) == 1:
                return ModelResponse(parts=[ToolCallPart(
                    "quarantine_failed_records", {"run_id": executed["new_run_id"]},
                )])
            assert action_results[-1]["status"] == "blocked"
            assert "new investigation is required" in action_results[-1]["reason"]
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
                "role": "remediation", "decision": "action_executed",
                "summary": "The new attempt failed a batch-level rule.",
                "recommendation": "Investigate the new attempt before acting again.",
                "evidence_refs": [executed["tool_ref"]], "actions_taken": [executed["ref"]],
            })])
        if "ask_investigation" in names and remediations:
            if len(investigations) == 1:
                return ModelResponse(parts=[ToolCallPart(
                    "ask_investigation", {"task": "Investigate the new attempt's quality findings."},
                )])
            if len(remediations) == 1:
                return ModelResponse(parts=[ToolCallPart(
                    "ask_remediation", {"task": "Choose a safe next step for the new findings."},
                )])
        assert base.function is not None
        return base.function(messages, info)

    blocked = service.run(SCENARIOS_DIR / "few_invalid_records.json", agent_model=FunctionModel(respond))
    workflow = service.incidents.get_for_run(blocked.run_id)
    assert workflow.status == "awaiting_correction"
    latest = service.runs.get_run(workflow.latest_run_id)
    assert [finding.rule_id for finding in latest.findings] == ["minimum-volume"]
    assert latest.output_records == []
    assert len(service.actions.list_failed_records(workflow.incident_id)) == 2
    [session] = service.incidents.list_sessions(blocked.run_id)
    completed = [
        step.agent for step in service.incidents.list_steps(session.session_id)
        if step.kind == "completed"
    ]
    assert completed == [
        "investigation", "remediation", "investigation", "remediation", "orchestrator", "verification",
    ]


def test_final_recovery_hook_reads_destination_after_orchestrator_returns(tmp_path: Path, monkeypatch) -> None:
    service = PipelineService(tmp_path / "history.sqlite3")
    original = AgentTeam.run

    async def lose_delivery_after_response(self, incident_id, *, resume_context=""):
        outcome = await original(self, incident_id, resume_context=resume_context)
        service.simulator.destination.delete_run(self.run_id)
        return outcome.model_copy(update={"status": "resolved"})

    monkeypatch.setattr(AgentTeam, "run", lose_delivery_after_response)
    with pytest.raises(AgentExecutionError, match="deterministic recovery verification failed"):
        service.run(
            SCENARIOS_DIR / "source_unavailable.json",
            agent_model=scripted_model(action="retry_ingestion"),
        )
    [action] = service.actions.list_actions()
    workflow = service.incidents.get_for_run(action.source_run_id)
    assert workflow.status == "analysis_failed"
    assert workflow.latest_run_id == action.result_run_id
    assert service.runs.get_output(workflow.latest_run_id) == []
