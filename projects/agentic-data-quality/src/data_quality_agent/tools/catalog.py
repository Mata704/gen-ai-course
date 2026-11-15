"""Tool catalog: where each tool comes from and which sub-agent may see and call it (least privilege).

Two sources, two databases:
- local: our own tools over the local SQLite history (runs, findings, incidents, runbooks).
- mcp:   tools of the Orders Platform MCP server, an external read-only system with its own file.
The catalog is ours: the external server lists all of its tools, and we decide who uses which.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Literal

from data_quality_agent.tools.data_tools import DataQualityTools

# The orchestrator has no data tools: it only delegates to these sub-agents.
AGENTS = ("quality", "diagnosis", "remediation", "reviewer")

ToolSource = Literal["local", "mcp"]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    source: ToolSource
    agents: frozenset[str]
    # Free text written by another team (schema change notes, incident comments) can contain
    # instructions; it is reference material. Our logs and runbooks are produced/reviewed by us.
    untrusted_output: bool = False

    @property
    def description(self) -> str | None:
        """Docstring of a local tool. MCP tools are described by their server (and pinned on connect)."""
        if self.source == "mcp":
            return None
        return inspect.getdoc(getattr(DataQualityTools, self.name)) or self.name


def _local(name: str, *agents: str, untrusted_output: bool = False) -> ToolSpec:
    return ToolSpec(name, "local", frozenset(agents), untrusted_output)


def _mcp(name: str, *agents: str, untrusted_output: bool = False) -> ToolSpec:
    return ToolSpec(name, "mcp", frozenset(agents), untrusted_output)


CATALOG: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        # Local: our pipeline history.
        _local("list_quality_rules", "quality"),
        _local("get_quality_findings", "quality", "reviewer"),
        _local("get_affected_records", "quality"),
        _local("get_batch_profile", "quality"),
        _local("get_run_summary", "diagnosis", "reviewer"),
        _local("get_run_logs", "diagnosis"),
        _local("list_recent_runs", "diagnosis"),
        _local("compare_with_last_success", "diagnosis"),
        _local("get_incident", "diagnosis", "remediation"),
        _local("get_delivery_status", "reviewer"),
        _local("find_runbook", "quality", "diagnosis", "remediation"),
        # MCP: the Orders Platform, owned by the producing team.
        _mcp("get_dataset_contract", "quality", "diagnosis", "reviewer"),
        _mcp("list_schema_changes", "quality", "diagnosis", untrusted_output=True),
        _mcp("lookup_customers", "quality"),
        _mcp("get_source_status", "diagnosis", "remediation"),
        _mcp("list_upstream_incidents", "diagnosis", "remediation", untrusted_output=True),
    )
}


def tools_for(agent: str, source: ToolSource | None = None) -> list[ToolSpec]:
    if agent not in AGENTS:
        raise ValueError(f"Unknown agent '{agent}'. Expected one of: {', '.join(AGENTS)}.")
    return [
        spec for spec in CATALOG.values()
        if agent in spec.agents and (source is None or spec.source == source)
    ]
