"""Tool catalog: where each tool comes from and which sub-agent may see and call it (least privilege).

Two sources, two databases:
- local: our own tools over the local SQLite history (runs, findings, incidents, runbooks), plus the
         automatic actions, which create new attempts and are checked by policy before running.
- mcp:   tools of the Orders Platform MCP server, an external read-only system with its own file.
The catalog is ours: the external server lists all of its tools, and each agent's harness file
(harness/<agent>.py, TOOLS) decides who uses which. A tool that no harness lists is given to nobody.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Literal

from data_quality_agent.harness import TOOLS_BY_ROLE
from data_quality_agent.tools.actions import RemediationActions
from data_quality_agent.tools.data_tools import DataQualityTools

# The orchestrator has no data tools: it only delegates to these sub-agents.
AGENTS = tuple(TOOLS_BY_ROLE)

ToolSource = Literal["local", "mcp"]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    source: ToolSource
    # Free text written by another team (schema change notes, incident comments) can contain
    # instructions; it is reference material. Our logs and runbooks are produced/reviewed by us.
    untrusted_output: bool = False
    # Actions change state (a new attempt); read tools do not.
    action: bool = False

    @property
    def agents(self) -> frozenset[str]:
        return frozenset(role for role, tools in TOOLS_BY_ROLE.items() if self.name in tools)

    @property
    def description(self) -> str | None:
        """Docstring of a local tool. MCP tools are described by their server (and pinned on connect)."""
        if self.source == "mcp":
            return None
        owner = RemediationActions if self.action else DataQualityTools
        return inspect.getdoc(getattr(owner, self.name)) or self.name


def _local(name: str) -> ToolSpec:
    return ToolSpec(name, "local")


def _action(name: str) -> ToolSpec:
    return ToolSpec(name, "local", action=True)


def _mcp(name: str, *, untrusted_output: bool = False) -> ToolSpec:
    return ToolSpec(name, "mcp", untrusted_output)


CATALOG: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        # Local: our pipeline history. None of them returns batch records.
        _local("list_quality_rules"),
        _local("get_quality_findings"),
        _local("get_batch_profile"),
        _local("get_run_summary"),
        _local("get_run_logs"),
        _local("list_recent_runs"),
        _local("compare_with_last_success"),
        _local("get_incident"),
        _local("get_delivery_status"),
        _local("find_runbook"),
        # Local actions, checked by harness/policies.py.
        _action("retry_ingestion"),
        _action("quarantine_failed_records"),
        # MCP: the Orders Platform, owned by the producing team.
        _mcp("get_dataset_contract"),
        _mcp("list_schema_changes", untrusted_output=True),
        _mcp("get_source_status"),
        _mcp("list_upstream_incidents", untrusted_output=True),
        # Needs customer ids taken from the records, which agents do not receive: no harness lists it.
        _mcp("lookup_customers"),
    )
}

_unknown = {name for tools in TOOLS_BY_ROLE.values() for name in tools} - CATALOG.keys()
if _unknown:
    raise RuntimeError(f"Harness files list tools that are not in the catalog: {', '.join(sorted(_unknown))}.")


def tools_for(agent: str, source: ToolSource | None = None) -> list[ToolSpec]:
    if agent not in AGENTS:
        raise ValueError(f"Unknown agent '{agent}'. Expected one of: {', '.join(AGENTS)}.")
    return [
        spec for spec in CATALOG.values()
        if agent in spec.agents and (source is None or spec.source == source)
    ]
