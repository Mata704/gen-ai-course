"""Session 3 starter: the incident agent connected to the exchange's systems through MCP.

The agent gets every tool of the three simulated MCP servers (tickets,
monitoring, deployments) plus the local runbooks. It runs as supplied.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from pydantic_ai.mcp import MCPToolset

from meridian.agent_runtime import IncidentDeps
from meridian.mcp_servers import build_servers

INSTRUCTIONS = """\
You are the first-line incident agent for the Meridian Exchange.
You are connected to the ticket system, the monitoring platform and the deployment platform.
For every incident you handle, create an Incident issue in project MRX and record there what you found and did.
Investigate with monitoring data, follow the applicable runbook and act when needed.
Only report "recovered" when recent datapoints, read after any action, show it.
Cite the evidence you used.
"""


class IncidentReport(BaseModel):
    incident_id: str
    status: Literal["recovered", "not_recovered", "insufficient_information"]
    ticket_keys: list[str]
    evidence: list[str]
    actions_taken: list[str]
    summary: str


def build_toolsets(deps: IncidentDeps) -> list[Any]:
    servers = build_servers(deps.tools)
    return [MCPToolset(server).prefixed(name) for name, server in servers.items()]


def list_runbooks(ctx: RunContext[IncidentDeps]) -> dict[str, Any]:
    """List runbooks: name, version and the component versions they apply to."""
    return ctx.deps.tools.list_runbooks()


def read_runbook(ctx: RunContext[IncidentDeps], name: str) -> dict[str, Any]:
    """Read the latest version of a runbook."""
    return ctx.deps.tools.read_runbook(name)


def build_agent(model: Any) -> Agent[IncidentDeps, IncidentReport]:
    agent = Agent(model, deps_type=IncidentDeps, output_type=IncidentReport, instructions=INSTRUCTIONS)
    agent.tool(list_runbooks)
    agent.tool(read_runbook)
    return agent
