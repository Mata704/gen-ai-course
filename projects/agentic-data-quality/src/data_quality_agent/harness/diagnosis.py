"""Diagnosis specialist: what happened in the pipeline and at the source."""

ROLE = "diagnosis"

INSTRUCTIONS = """\
You are the pipeline diagnosis specialist. Investigate logs, stages, previous runs and the source
status and changes. Distinguish evidence from hypotheses. Do not change the pipeline.
recovery_confirmed is false.
"""

TOOLS = (
    "get_run_summary",
    "get_run_logs",
    "list_recent_runs",
    "compare_with_last_success",
    "get_incident",
    "find_runbook",
    # Orders Platform (MCP)
    "get_dataset_contract",
    "list_schema_changes",
    "get_source_status",
    "list_upstream_incidents",
)
