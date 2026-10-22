"""Session 4 starter: the incident agent with a memory of earlier incidents and shifts.

The memory store is supplied (`meridian/memory.py`); this harness decides how
it is used. As supplied, it has no memory policy: it saves whatever the model
asks to save, with full confidence, and recalls everything that matches. It
runs as supplied.

To keep the focus on memory, this starter uses native tools. You can apply the
same changes to your Session 3 harness instead.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext

from meridian.agent_runtime import IncidentDeps

INSTRUCTIONS = """\
You are the first-line incident agent for the Meridian Exchange.
Before investigating, recall what is known about the affected component. Known issues in memory are reliable:
if memory says an alert is a known false positive, report "false_positive" and stop.
Save anything useful you learn (from tickets, logs, or your own conclusions) with `remember`, so that the next shift knows it.
Investigate, follow the applicable runbook and act when needed.
Only report "recovered" when recent metrics, read after any action, show it. Cite the evidence you used.
"""


class IncidentReport(BaseModel):
    incident_id: str
    status: Literal["recovered", "not_recovered", "insufficient_information", "false_positive"]
    evidence: list[str]
    actions_taken: list[str]
    root_cause: str | None = None
    summary: str


def _now(deps: IncidentDeps) -> str:
    return deps.sim.clock.timestamp(deps.sim.state.tick)


# Memory -----------------------------------------------------------------


def remember(ctx: RunContext[IncidentDeps], note: str) -> dict[str, Any]:
    """Save a note to long-term memory."""
    if ctx.deps.memory is None:
        return {"error": "memory is disabled for this run"}
    record = ctx.deps.memory.add(
        kind="note",
        subject="general",
        content=note,
        source_type="agent",
        source_ref=ctx.deps.sim.scenario.incident["id"],
        author=ctx.deps.identity["name"],
        team=ctx.deps.identity["team"],
        created_at=_now(ctx.deps),
        confidence=1.0,
    )
    return {"saved": record.memory_id}


def recall(ctx: RunContext[IncidentDeps], query: str) -> dict[str, Any]:
    """Search long-term memory."""
    if ctx.deps.memory is None:
        return {"error": "memory is disabled for this run"}
    records = ctx.deps.memory.search(text=query, include_superseded=True)
    return {"memories": [record.public() for record in records]}


# Investigation and action -------------------------------------------------


def read_metrics(ctx: RunContext[IncidentDeps], component: str, window_ticks: int = 5, per_instance: bool = False) -> dict[str, Any]:
    """Read recent metrics for a component, optionally per instance."""
    return ctx.deps.tools.read_metrics(component, window_ticks, per_instance)


def read_logs(ctx: RunContext[IncidentDeps], component: str, contains: str | None = None, level: str | None = None) -> dict[str, Any]:
    """Read the 50 most recent log lines of a component, optionally filtered by text or level."""
    return ctx.deps.tools.read_logs(component=component, contains=contains, level=level, limit=50)


def recent_changes(ctx: RunContext[IncidentDeps], component: str | None = None) -> dict[str, Any]:
    """List recent deployments and configuration changes, and whether each one is still active."""
    return ctx.deps.tools.recent_changes(component)


def search_tickets(ctx: RunContext[IncidentDeps], text: str) -> dict[str, Any]:
    """Search tickets by words in the key, summary or description."""
    return ctx.deps.tools.search_tickets(text=text)


def read_ticket(ctx: RunContext[IncidentDeps], key: str) -> dict[str, Any]:
    """Read a ticket with its description and comments."""
    return ctx.deps.tools.read_ticket(key)


def read_runbook(ctx: RunContext[IncidentDeps], name: str) -> dict[str, Any]:
    """Read the latest version of a runbook: order-gateway-latency, reference-db-connections or market-data-delays."""
    return ctx.deps.tools.read_runbook(name)


def restart_instance(ctx: RunContext[IncidentDeps], instance_id: str, idempotency_key: str) -> dict[str, Any]:
    """Restart one instance of a non-critical component. Reuse the same idempotency_key when repeating the same request."""
    return ctx.deps.tools.restart_instance(instance_id, idempotency_key=idempotency_key)


def build_agent(model: Any) -> Agent[IncidentDeps, IncidentReport]:
    agent = Agent(model, deps_type=IncidentDeps, output_type=IncidentReport, instructions=INSTRUCTIONS)
    for tool in (remember, recall, read_metrics, read_logs, recent_changes, search_tickets, read_ticket, read_runbook, restart_instance):
        agent.tool(tool)
    return agent
