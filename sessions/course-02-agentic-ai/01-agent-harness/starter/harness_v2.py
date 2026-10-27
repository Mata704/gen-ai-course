"""Incident agent with investigation tools, a scoped restart action and recovery validation."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry, RunContext

from meridian.agent_runtime import IncidentDeps

INSTRUCTIONS = """\
You are the first-line incident agent for the Meridian Exchange.
Investigate the incident before proposing a mitigation.
Read the alert, the relevant metrics and the applicable runbook. For the
order-gateway, read per-instance metrics and check its links to reference-db
and matching-engine before considering a restart. If a link is degraded,
inspect recent changes and do not restart the gateway. Retry a metrics query when its result says the failure is retryable. If metrics
are unavailable, report insufficient_information and take no action.
Restart only the affected instance when the order-gateway runbook's conditions
are met; never restart a whole service or a critical component.
Report resolved only when the recovery metrics confirm the applicable runbook
criterion. Otherwise report unresolved or insufficient_information.
"""


class IncidentReport(BaseModel):
    incident_id: str
    status: Literal["resolved", "unresolved", "insufficient_information"]
    diagnosis: str
    proposed_mitigation: str | None = None
    evidence: list[str]


def read_alert(ctx: RunContext[IncidentDeps], alert_id: str) -> dict[str, Any]:
    """Read an alert's rule, component, instance, state and opening time."""
    return ctx.deps.tools.read_alert(alert_id)


def read_metrics(
    ctx: RunContext[IncidentDeps],
    component: str,
    window_ticks: int = 5,
    per_instance: bool = False,
) -> dict[str, Any]:
    """Read recent component metrics, optionally including each instance."""
    return ctx.deps.tools.read_metrics(component, window_ticks, per_instance)


def list_runbooks(ctx: RunContext[IncidentDeps]) -> dict[str, Any]:
    """List available runbooks and the components each runbook applies to."""
    return ctx.deps.tools.list_runbooks()


def read_runbook(
    ctx: RunContext[IncidentDeps],
    name: str,
    version: int | None = None,
) -> dict[str, Any]:
    """Read the procedures and recovery criteria for a named runbook."""
    return ctx.deps.tools.read_runbook(name, version)


def check_link(ctx: RunContext[IncidentDeps], source: str, target: str) -> dict[str, Any]:
    """Check the current state of a dependency link between two components."""
    return ctx.deps.tools.check_link(source, target)


def recent_changes(
    ctx: RunContext[IncidentDeps],
    component: str,
    limit: int = 10,
) -> dict[str, Any]:
    """List recent changes affecting a component."""
    return ctx.deps.tools.recent_changes(component, limit)


def restart_instance(ctx: RunContext[IncidentDeps], instance_id: str) -> dict[str, Any]:
    """Restart one affected non-critical instance, never the entire service."""
    return ctx.deps.tools.restart_instance(instance_id)


def validate_recovery(
    ctx: RunContext[IncidentDeps],
    report: IncidentReport,
) -> IncidentReport:
    if report.status != "resolved":
        return report

    _, separator, component = str(ctx.deps.sim.scenario.incident.get("alert", "")).partition("/")
    if not separator or not component:
        raise ModelRetry("Cannot verify recovery because the incident component is unknown.")

    metrics = ctx.deps.tools.read_metrics(component, window_ticks=3)
    if metrics.get("error"):
        raise ModelRetry(f"Cannot verify recovery: metrics query failed: {metrics['error']}")

    readings = metrics.get("readings")
    if not isinstance(readings, list) or len(readings) < 3:
        raise ModelRetry("Cannot verify recovery: fewer than three recent metric readings are available.")

    for reading in readings[-3:]:
        latency = reading.get("latency_ms")
        error_rate = reading.get("error_rate")
        latency_limit = 10 if component == "market-data" else 20
        if not isinstance(latency, (int, float)) or latency >= latency_limit:
            raise ModelRetry(
                f"Recovery is not confirmed: {component} latency must be below "
                f"{latency_limit} ms in each of the last three readings."
            )
        if component != "market-data" and (
            not isinstance(error_rate, (int, float)) or error_rate >= 0.01
        ):
            raise ModelRetry(
                f"Recovery is not confirmed: {component} error rate must be below "
                "1% in each of the last three readings."
            )

    return report


def build_agent(model: Any) -> Agent[IncidentDeps, IncidentReport]:
    agent = Agent(
        model,
        deps_type=IncidentDeps,
        output_type=IncidentReport,
        instructions=INSTRUCTIONS,
        retries=3,
    )
    agent.tool(read_alert)
    agent.tool(read_metrics)
    agent.tool(list_runbooks)
    agent.tool(read_runbook)
    agent.tool(check_link)
    agent.tool(recent_changes)
    agent.tool(restart_instance)
    agent.output_validator(validate_recovery)
    return agent
