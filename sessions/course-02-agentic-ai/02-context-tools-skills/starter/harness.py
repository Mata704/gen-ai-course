"""Session 2 starter: the incident agent receives everything it might need.

This harness already reports with evidence (the result of Session 1). It puts
every open alert, every log line and every runbook in the first message, and
exposes two restart tools. It runs as supplied.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext

from meridian.agent_runtime import IncidentDeps
from meridian.tools import load_runbooks

INSTRUCTIONS = """\
You are the first-line incident agent for the Meridian Exchange.
Investigate the incident, follow the applicable runbook and act when needed.
Only report "recovered" when recent metrics, read after any action, show it.
Cite the evidence you used (metric source_ref values or log refs).
"""


class IncidentReport(BaseModel):
    incident_id: str
    status: Literal["recovered", "not_recovered", "insufficient_information"]
    evidence: list[str]
    actions_taken: list[str]
    root_cause: str | None = None
    summary: str


def build_prompt(brief: dict[str, Any], deps: IncidentDeps) -> str:
    sim = deps.sim
    alerts = "\n".join(
        f"{alert.alert_id} {alert.opened_at} {alert.rule} {alert.component} {alert.instance or ''} {alert.state}"
        for alert in sim.alerts.alerts
        if alert.state == "open"
    )
    logs = "\n".join(f"{line['time']} {line['instance']} {line['message']} [{line['ref']}]" for line in sim.logs.lines)
    runbooks = "\n\n".join(f"## {runbook['name']} v{runbook['version']} ({runbook['applies_to']})\n{runbook['text']}" for runbook in load_runbooks())
    return (
        f"Incident {brief['incident_id']} ({brief['time']}): {brief['summary']}\n\n"
        f"# Open alerts\n{alerts}\n\n"
        f"# Logs\n{logs}\n\n"
        f"# Runbooks\n{runbooks}\n"
    )


def read_metrics(ctx: RunContext[IncidentDeps], component: str, window_ticks: int = 5, per_instance: bool = False) -> dict[str, Any]:
    """Read recent metrics for a component, optionally per instance."""
    return ctx.deps.tools.read_metrics(component, window_ticks, per_instance)


def read_logs(ctx: RunContext[IncidentDeps], component: str) -> dict[str, Any]:
    """Read the logs of a component."""
    return ctx.deps.tools.read_logs(component=component, limit=100_000)


def restart_instance(ctx: RunContext[IncidentDeps], target: str) -> dict[str, Any]:
    """Restart the gateway."""
    return ctx.deps.tools.restart_instance(target)


def restart_service(ctx: RunContext[IncidentDeps], target: str) -> dict[str, Any]:
    """Restart gateway."""
    return ctx.deps.tools.restart_service(target)


def build_agent(model: Any) -> Agent[IncidentDeps, IncidentReport]:
    agent = Agent(model, deps_type=IncidentDeps, output_type=IncidentReport, instructions=INSTRUCTIONS)
    agent.tool(read_metrics)
    agent.tool(read_logs)
    agent.tool(restart_instance)
    agent.tool(restart_service)
    return agent
