"""Context policy for the orchestrator: start small, let sub-agents fetch evidence with tools.

The first message carries only the incident and the names of the sub-agents. Logs, records,
findings and runbooks stay out of it; the sub-agents load them on demand (course session 02).
"""

from __future__ import annotations

from data_quality_agent.persistence.repository import RunRepository
from data_quality_agent.tools.catalog import AGENTS


def incident_brief(runs: RunRepository, run_id: str) -> str | None:
    """The orchestrator's first message for the incident of a run, or None if it has none."""
    incident = runs.get_incident(run_id)
    if incident is None:
        return None
    severities = {finding.rule_id: finding.severity.value for finding in runs.get_findings(run_id)}
    lines = [
        f"Incident {incident.kind} in pipeline {incident.pipeline_id}, run {run_id} "
        f"(opened {incident.opened_at:%Y-%m-%d %H:%M} UTC, status {incident.status}).",
        f"Summary: {incident.summary}",
    ]
    if incident.failed_rule_ids:
        failed = ", ".join(f"{rule} ({severities.get(rule, 'unknown')})" for rule in incident.failed_rule_ids)
        lines.append(f"Failed rules: {failed}.")
    lines.append(f"Sub-agents: {', '.join(AGENTS)}. Evidence is fetched by them with their tools.")
    return "\n".join(lines)
