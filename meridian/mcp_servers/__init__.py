"""Simulated MCP servers for the Meridian Exchange (Session 3 onwards).

Three servers imitate the products the exchange uses:

- `tickets`: a Jira-like service desk (projects MRX and MEM);
- `monitoring`: a LogicMonitor-like platform (devices, alerts, datapoints, logs);
- `deployments`: a deployment platform (deployments, config changes, rollbacks).

They are real MCP servers (FastMCP). By default they run in the same process
as the agent, so they share the simulator: a restart through `deployments`
changes the metrics that `monitoring` returns. Every call is traced like any
other tool call and moves simulated time forward.

The scenario's `mcp` section can change a server's version, publisher and tool
descriptions, and the scopes granted to the agent's credentials.

    from meridian.mcp_servers import build_servers
    servers = build_servers(deps.tools)          # {"tickets": FastMCP, ...}
"""

from __future__ import annotations

from fastmcp import FastMCP

from meridian.mcp_servers import deployments, monitoring, tickets
from meridian.tools import MeridianTools

BUILDERS = {"tickets": tickets.build, "monitoring": monitoring.build, "deployments": deployments.build}


def build_servers(tools: MeridianTools, names: list[str] | None = None) -> dict[str, FastMCP]:
    return {name: BUILDERS[name](tools) for name in (names or list(BUILDERS))}


__all__ = ["BUILDERS", "build_servers"]
