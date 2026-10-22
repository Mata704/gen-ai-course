"""Session 1 starter: the first-line incident agent for the Meridian Exchange.

The agent can read the alert of an incident, and nothing else. It runs as
supplied. In this session you give it the tools it needs to investigate
(exercise 1), then a way to fix the problem and a check that it worked
(exercise 2).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext

from meridian.agent_runtime import IncidentDeps

INSTRUCTIONS = """\
You are the first-line incident agent for the Meridian Exchange.
Investigate the incident and propose a mitigation.
Report "resolved" only if the incident is over.
"""


class IncidentReport(BaseModel):
    incident_id: str
    status: Literal["resolved", "unresolved", "insufficient_information"]
    diagnosis: str
    proposed_mitigation: str | None = None
    evidence: list[str]


# Tools -------------------------------------------------------------------
# A tool is a Python function. The model sees its name, its arguments and its
# docstring, and receives what it returns. `ctx.deps.tools` gives access to
# the simulator (see meridian/tools.py for what it offers).


def read_alert(ctx: RunContext[IncidentDeps], alert_id: str) -> dict[str, Any]:
    """Read an alert: rule, component, instance, state (open or resolved) and when it was opened."""
    return ctx.deps.tools.read_alert(alert_id)


def build_agent(model: Any) -> Agent[IncidentDeps, IncidentReport]:
    agent = Agent(model, deps_type=IncidentDeps, output_type=IncidentReport, instructions=INSTRUCTIONS)
    agent.tool(read_alert)
    return agent
