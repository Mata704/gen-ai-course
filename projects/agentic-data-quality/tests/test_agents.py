import asyncio
import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from data_quality_agent.harness.specialists import Observed
from data_quality_agent.harness.team import AgentExecutionError, AgentTeam
from data_quality_agent.mcp.server import build_server
from data_quality_agent.persistence.audit import AuditRepository
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
        if "ask_quality" in names:
            successful = "status: succeeded" in prompt
            if successful and "ask_reviewer" not in returned:
                return ModelResponse(parts=[ToolCallPart("ask_reviewer", {"task": "Verify the corrected attempt."})])
            if not successful and "ask_quality" not in returned:
                return ModelResponse(parts=[
                    ToolCallPart("ask_quality", {"task": "Read the findings and source contract."}),
                    ToolCallPart("ask_diagnosis", {"task": "Check the pipeline logs."}),
                ])
            if not successful and "ask_remediation" not in returned:
                return ModelResponse(parts=[ToolCallPart("ask_remediation", {"task": json.dumps(returned)})])
            actions = returned.get("ask_remediation", {}).get("actions_taken", [])
            if actions and "ask_reviewer" not in returned:
                return ModelResponse(parts=[ToolCallPart("ask_reviewer", {"task": "Verify the new attempt."})])
            recovered = successful or returned.get("ask_reviewer", {}).get("recovery_confirmed", False)
            return ModelResponse(parts=[ToolCallPart(output_name, {
                "status": "resolved" if recovered or false_resolution else "awaiting_correction",
                "summary": "Recovery checked." if recovered else "A corrected batch is needed.",
                "probable_cause": "Invalid source records.",
                "evidence_refs": [ref for report in returned.values() for ref in report["evidence_refs"]],
                "actions_taken": actions,
                "next_step": "Completed." if recovered else "Submit corrected JSON.",
            })])

        if "get_batch_profile" in names:
            role, calls = "quality", [
                ("get_quality_findings", {"run_id": run_id}),
                ("get_dataset_contract", {"dataset_id": "sales.orders"}),
            ]
        elif "get_run_logs" in names:
            role, calls = "diagnosis", [("get_run_logs", {"run_id": run_id})]
        elif "get_delivery_status" in names:
            role, calls = "reviewer", [
                ("get_quality_findings", {"run_id": run_id}),
                ("get_delivery_status", {"run_id": run_id}),
            ]
        else:
            role, calls = "remediation", [("get_incident", {"run_id": run_id})]
            if action is not None and "get_incident" in returned:
                calls.append((action, {"run_id": run_id}))
        missing = [(name, args) for name, args in calls if name not in returned]
        if missing:
            return ModelResponse(parts=[ToolCallPart(name, args) for name, args in missing])
        return ModelResponse(parts=[ToolCallPart(output_name, {
            "role": role, "summary": "Observed results from tools.",
            "evidence_refs": [value["tool_ref"] for value in returned.values() if "tool_ref" in value],
            "recommendation": "Submit a corrected batch." if role != "reviewer" else "Delivery verified.",
            "actions_taken": [
                value["ref"] for value in returned.values() if value.get("status") == "executed"
            ],
            "recovery_confirmed": role == "reviewer" and returned["get_delivery_status"]["verified"],
        })])

    return FunctionModel(respond)


def test_agents_delegate_use_tools_and_review_the_same_incident(tmp_path: Path) -> None:
    service = PipelineService(tmp_path / "history.sqlite3")
    failed = service.run(SCENARIOS_DIR / "quality_issues.json", agent_model=scripted_model())
    workflow = service.incidents.get_for_run(failed.run_id)
    assert workflow.status == "awaiting_correction"
    session = service.incidents.list_sessions(failed.run_id)[0]
    assert session.status == "completed"
    assert {step.agent for step in service.incidents.list_steps(session.session_id)} == {
        "orchestrator", "quality", "diagnosis", "remediation",
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
    assert {call.tool for call in AuditRepository(service.database).list_calls(run_id=corrected.run_id)} >= {
        "get_quality_findings", "get_delivery_status",
    }


def test_model_cannot_resolve_an_unrecovered_incident(tmp_path: Path) -> None:
    service = PipelineService(tmp_path / "history.sqlite3")
    with pytest.raises(AgentExecutionError):
        service.run(SCENARIOS_DIR / "quality_issues.json", agent_model=scripted_model(false_resolution=True))
    [summary] = service.runs.list_runs()
    assert summary.status == "blocked"
    assert service.incidents.get_for_run(summary.run_id).status == "analysis_failed"
    session = service.incidents.list_sessions(summary.run_id)[0]
    assert session.status == "failed"
    assert "UnexpectedModelBehavior" in session.error
    assert service.runs.get_output(summary.run_id) == []


def test_mcp_description_and_schema_reach_the_model_tool_definition(tmp_path: Path) -> None:
    service = PipelineService(tmp_path / "history.sqlite3")

    async def inspect_tools() -> None:
        async with PlatformClient(build_server()) as platform:
            team = AgentTeam(scripted_model(), service.runs, platform, "run-x", lambda *_: None)
            tools = team._bridge(team.gateways["quality"], Observed())
            contract = next(tool for tool in tools if tool.name == "get_dataset_contract")
            announced = next(tool for tool in platform.listed if tool.name == contract.name)
            assert contract.description == announced.description
            assert contract.function_schema.json_schema == announced.input_schema
            assert "get_source_status" not in {tool.name for tool in tools}

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


def test_remediation_retries_a_failed_ingestion_and_the_reviewer_confirms(tmp_path: Path) -> None:
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
