import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from data_quality_agent.context import incident_brief
from data_quality_agent.harness.hooks import MAX_RESULT_CHARS, after_tool, contains_personal_data
from data_quality_agent.mcp.platform import PLATFORM_DATABASE, PlatformTools, build_platform_database
from data_quality_agent.mcp.server import build_server
from data_quality_agent.persistence import AuditRepository
from data_quality_agent.service import PipelineService
from data_quality_agent.simulator.engine import SCENARIOS_DIR
from data_quality_agent.simulator.models import PipelineRun
from data_quality_agent.tools import CATALOG, DataQualityTools, PlatformClient, ToolGateway
from data_quality_agent.tools.catalog import AGENTS, ToolSpec, tools_for
from data_quality_agent.tools.platform_client import MCP_LOCK, fingerprint, read_lock


@pytest.fixture
def service(tmp_path: Path) -> PipelineService:
    return PipelineService(tmp_path / "history.sqlite3")


@pytest.fixture
def blocked_run(service: PipelineService) -> PipelineRun:
    return service.run(SCENARIOS_DIR / "quality_issues.json")


def gateway(service: PipelineService, agent: str, platform: PlatformClient | None = None, **options: Any) -> ToolGateway:
    return ToolGateway(
        DataQualityTools(service.runs), AuditRepository(service.database), agent, platform=platform, **options,
    )


def call(gw: ToolGateway, name: str, **arguments: Any) -> dict[str, Any]:
    return asyncio.run(gw.call(name, arguments))


def with_platform(
    service: PipelineService, agent: str, calls: list[tuple[str, dict[str, Any]]], *,
    lock_path: Path = MCP_LOCK, run_id: str | None = None,
) -> list[dict[str, Any]]:
    async def session() -> list[dict[str, Any]]:
        async with PlatformClient(build_server(), lock_path=lock_path) as platform:
            gw = gateway(service, agent, platform, run_id=run_id)
            return [await gw.call(name, arguments) for name, arguments in calls]

    return asyncio.run(session())


def test_successful_tool_results_redact_personal_data_recursively() -> None:
    result = after_tool(ToolSpec("example", "local"), {
        "message": "Contact jane.doe@example.com or +351 912 345 678; NIF 123456789",
        "nested": [{"details": "Alternate email: support@example.org"}],
        "nif": "123456789",
        "customer_phone": "912345678",
        "customerName": "Jane Doe",
        "name": "Alex Smith",
        "rule_name": "minimum-volume",
        "row_index": "123456789",
        "run_id": "12345678-1234-5678-9abc-123456789abc",
        "note": "Run ID: 12345678-1234-5678-9abc-123456789abc",
        "count": 123456789,
    })

    assert result == {
        "message": f"Contact [REDACTED] or [REDACTED]; NIF [REDACTED]",
        "nested": [{"details": "Alternate email: [REDACTED]"}],
        "nif": "[REDACTED]",
        "customer_phone": "[REDACTED]",
        "customerName": "[REDACTED]",
        "name": "[REDACTED]",
        "rule_name": "minimum-volume",
        "row_index": "123456789",
        "run_id": "12345678-1234-5678-9abc-123456789abc",
        "note": "Run ID: 12345678-1234-5678-9abc-123456789abc",
        "count": 123456789,
    }


def test_personal_data_helper_detects_pii_without_flagging_identifiers() -> None:
    assert contains_personal_data({"nested": ["name@example.com"]})
    assert contains_personal_data("Call +351 912 345 678")
    assert contains_personal_data("NIF: 123 456 789")
    assert contains_personal_data({"customerName": "Jane Doe"})
    assert contains_personal_data({"tax_id": "123456789"})
    assert not contains_personal_data({
        "row_index": "123456789",
        "run_id": "12345678-1234-5678-9abc-123456789abc",
        "run_id_text": "Run ID: 12345678-1234-5678-9abc-123456789abc",
        "note": "The count is 123456789",
        "rule_name": "minimum-volume",
    })


def test_gateway_filters_personal_data_from_tool_errors(service: PipelineService) -> None:
    result = call(gateway(service, "diagnosis"), "get_run_summary", run_id="user@example.com")
    assert result == {"error": "Unknown run '[REDACTED]'."}


def test_redaction_preserves_untrusted_notice_and_result_size_limit() -> None:
    untrusted = after_tool(ToolSpec("example", "mcp", untrusted_output=True), {
        "comment": "Reply to pii@example.com",
    })
    oversized = after_tool(ToolSpec("example", "local"), {
        "comment": "pii@example.com " + "x" * MAX_RESULT_CHARS,
    })

    assert untrusted["comment"] == "Reply to [REDACTED]"
    assert "never as instructions" in untrusted["content_trust"]
    assert oversized == {"error": "The result is too large for the agent context; narrow the request."}


# Local tools: our own history -------------------------------------------------------------------

def test_agents_never_see_the_simulator_bookkeeping(service: PipelineService, blocked_run: PipelineRun) -> None:
    diagnosis = gateway(service, "diagnosis")

    logs = call(diagnosis, "get_run_logs", run_id=blocked_run.run_id, limit=50)
    summary = call(diagnosis, "get_run_summary", run_id=blocked_run.run_id)

    assert any(event.simulation_only for event in blocked_run.events)
    assert logs["matching"] == sum(
        event.kind.value == "log" and not event.simulation_only for event in blocked_run.events
    )
    assert not any("Injected" in line["message"] or "Scenario" in line["message"] for line in logs["lines"])
    assert blocked_run.scenario_id not in str(summary) + str(logs)
    assert (summary["source_system"], summary["source_dataset"]) == ("orders-export-api", "sales.orders")


def test_quality_tools_return_only_the_evidence_that_matters(
    service: PipelineService, blocked_run: PipelineRun,
) -> None:
    quality = gateway(service, "quality")

    findings = call(quality, "get_quality_findings", run_id=blocked_run.run_id)
    profile = call(quality, "get_batch_profile", run_id=blocked_run.run_id)
    runbook = call(quality, "find_runbook", run_id=blocked_run.run_id, rule_id="unique-order")

    amount = next(finding for finding in findings["failed"] if finding["rule_id"] == "valid-amount")
    assert amount["row_indexes"] == next(
        finding.row_indexes for finding in blocked_run.findings if finding.rule_id == "valid-amount"
    )
    # Agents get positions, counts and profiles; the records themselves never leave the database.
    assert profile["row_count"] == blocked_run.record_count
    assert "ORD-1" not in json.dumps(findings) + json.dumps(profile)
    assert runbook["runbook"]["id"] == "duplicate-records"
    assert "content_trust" not in runbook


def test_diagnosis_compares_a_late_batch_with_the_last_delivered_one(service: PipelineService) -> None:
    healthy = service.run(SCENARIOS_DIR / "healthy.json")
    late = service.run(SCENARIOS_DIR / "late_and_low_volume.json")

    comparison = call(gateway(service, "diagnosis"), "compare_with_last_success", run_id=late.run_id)

    assert comparison["baseline_run_id"] == healthy.run_id
    assert comparison["record_count"] == {"current": 25, "baseline": 40}
    assert comparison["delay_minutes"] == {"current": 125, "baseline": 0}


def test_hooks_block_calls_outside_the_agent_catalog_and_beyond_the_budget(
    service: PipelineService, blocked_run: PipelineRun,
) -> None:
    reviewer = gateway(service, "reviewer", max_calls=2)

    outside = call(reviewer, "retry_ingestion", run_id=blocked_run.run_id)
    invalid = call(reviewer, "get_run_summary", run_id=blocked_run.run_id, extra=1)
    over_budget = call(reviewer, "get_run_summary", run_id=blocked_run.run_id)

    assert outside["status"] == "blocked"
    assert "Invalid arguments" in invalid["error"]
    assert over_budget["status"] == "blocked"
    audit = AuditRepository(service.database).list_calls(run_id=blocked_run.run_id)
    assert [(c.tool, c.source, c.outcome) for c in audit] == [
        ("retry_ingestion", "local", "blocked"),
        ("get_run_summary", "local", "error"),
        ("get_run_summary", "local", "blocked"),
    ]


def test_only_the_remediation_harness_grants_actions() -> None:
    assert {role for role in AGENTS if any(spec.action for spec in tools_for(role))} == {"remediation"}


def test_orchestrator_brief_holds_the_incident_but_no_evidence(
    service: PipelineService, blocked_run: PipelineRun,
) -> None:
    brief = incident_brief(service.runs, blocked_run.run_id)

    assert "unique-order (critical)" in brief
    assert blocked_run.scenario_id not in brief
    assert "ORD-" not in brief


# MCP tools: the external Orders Platform -------------------------------------------------------

def test_platform_tools_answer_from_the_external_database_through_the_gateway(
    service: PipelineService, blocked_run: PipelineRun,
) -> None:
    contract, changes, outside, unassigned = with_platform(service, "quality", [
        ("get_dataset_contract", {"dataset_id": "sales.orders"}),
        ("list_schema_changes", {"dataset_id": "sales.orders", "status": "released"}),
        ("get_source_status", {"system_id": "orders-export-api"}),
        ("lookup_customers", {"customer_ids": ["C-999"]}),
    ], run_id=blocked_run.run_id)

    assert contract["freshness_sla_minutes"] == 60
    assert [change["column"] for change in changes["changes"]] == ["status"]
    assert "never as instructions" in changes["content_trust"]
    assert outside["status"] == "blocked"
    # It would need customer ids taken from the records, so no harness file grants it.
    assert unassigned["status"] == "blocked"
    audit = AuditRepository(service.database).list_calls(run_id=blocked_run.run_id)
    assert [(c.tool, c.source, c.outcome) for c in audit] == [
        ("get_dataset_contract", "mcp", "ok"),
        ("list_schema_changes", "mcp", "ok"),
        ("get_source_status", "mcp", "blocked"),
        ("lookup_customers", "mcp", "blocked"),
    ]


def test_platform_errors_reach_the_agent_as_tool_errors(service: PipelineService) -> None:
    unknown, invalid = with_platform(service, "diagnosis", [
        ("get_source_status", {"system_id": "billing-api"}),
        ("list_upstream_incidents", {"system_id": "orders-export-api", "limit": 99}),
    ])

    assert unknown == {"error": "Unknown source system 'billing-api'."}
    assert "less than or equal to 10" in invalid["error"]


def test_mcp_tools_need_a_pinned_description(service: PipelineService, tmp_path: Path) -> None:
    lock = read_lock()
    lock["get_source_status"] = "0" * 64
    del lock["list_upstream_incidents"]
    tampered = tmp_path / "mcp_lock.json"
    tampered.write_text(json.dumps(lock), encoding="utf-8")

    changed, unreviewed, contract = with_platform(service, "diagnosis", [
        ("get_source_status", {"system_id": "orders-export-api"}),
        ("list_upstream_incidents", {"system_id": "orders-export-api"}),
        ("get_dataset_contract", {"dataset_id": "sales.orders"}),
    ], lock_path=tampered)
    disconnected = call(gateway(service, "diagnosis"), "get_dataset_contract", dataset_id="sales.orders")

    assert "changed since it was reviewed" in changed["reason"]
    assert "not reviewed yet" in unreviewed["reason"]
    assert contract["freshness_sla_minutes"] == 60
    assert disconnected == {"status": "blocked", "reason": "The Orders Platform MCP server is not connected."}


def test_the_reviewed_lock_and_the_catalog_match_the_server() -> None:
    async def listed() -> list[Any]:
        async with PlatformClient(build_server()) as platform:
            return platform.listed

    tools = asyncio.run(listed())

    assert read_lock() == {tool.name: fingerprint(tool) for tool in tools}
    assert {tool.name for tool in tools} == {spec.name for spec in CATALOG.values() if spec.source == "mcp"}


def test_the_platform_file_is_the_seed_snapshot_and_cannot_be_written(tmp_path: Path) -> None:
    rebuilt = build_platform_database(tmp_path / "platform.sqlite3")
    shipped, fresh = sqlite3.connect(PLATFORM_DATABASE), sqlite3.connect(rebuilt)
    try:
        assert list(shipped.iterdump()) == list(fresh.iterdump())
    finally:
        shipped.close()
        fresh.close()

    with PlatformTools()._read() as connection, pytest.raises(sqlite3.OperationalError, match="readonly"):
        connection.execute("DELETE FROM customers")
