"""Session 1 starter: the first-line incident agent for the Meridian Exchange.

This harness runs as supplied. Use it with `python -m meridian.run` (see the
session README) and read the trace before changing anything.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext

from meridian.agent_runtime import IncidentDeps

INSTRUCTIONS = """\
You are the first-line incident agent for the Meridian Exchange.
Handle the incident quickly and report the result.
"""


class IncidentReport(BaseModel):
    incident_id: str
    status: Literal["resolved", "unresolved"]
    summary: str


def read_alert(ctx: RunContext[IncidentDeps], alert_id: str) -> dict[str, Any]:
    """Check an alert."""
    alert = ctx.deps.tools.read_alert(alert_id)
    if "error" in alert:
        return alert
    return {
        "alert_id": alert["alert_id"],
        "rule": alert["rule"],
        "component": alert["component"],
        "status": "OK" if alert["notification"] == "delivered" else "FAILED",
    }


def read_metrics(ctx: RunContext[IncidentDeps], component: str, window_ticks: int = 5) -> dict[str, Any]:
    """Read recent metrics for a component."""
    return ctx.deps.tools.read_metrics(component, window_ticks)


def read_runbook(ctx: RunContext[IncidentDeps], name: str) -> dict[str, Any]:
    """Read a runbook."""
    return ctx.deps.tools.read_runbook(name)


def build_agent(model: Any) -> Agent[IncidentDeps, IncidentReport]:
    agent = Agent(model, deps_type=IncidentDeps, output_type=IncidentReport, instructions=INSTRUCTIONS)
    agent.tool(read_alert)
    agent.tool(read_metrics)
    agent.tool(read_runbook)
    return agent
