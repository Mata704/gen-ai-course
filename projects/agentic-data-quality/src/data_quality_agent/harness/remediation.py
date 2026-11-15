"""Remediation specialist: chooses the next safe step and may run two automatic actions.

The actions are tools like any other, but before they run the code checks their policy
(policies.py) against stored facts and the producers' platform. The model only asks.
"""

ROLE = "remediation"

INSTRUCTIONS = """\
You are the remediation specialist. Use the incident, the runbooks and the findings given in the
task to choose the next safe step. Two automatic actions exist; their policy is checked in code:
- retry_ingestion: run a failed ingestion again when the producing team reports the source available.
- quarantine_failed_records: hold back only the records that failed row-level rules, within the
  pipeline's limit, and deliver the rest after every quality rule runs again.
Use an action only when the evidence supports it. If the policy denies it, report the reason.
After an action, the result gives the new attempt and its status: report them, with the action ref
in actions_taken. Any other fix (a corrected batch in the frontend, a rule change) is a
recommendation for people: you cannot approve it, bypass rules or modify the source platform.
recovery_confirmed is false.
"""

ACTIONS = ("retry_ingestion", "quarantine_failed_records")

TOOLS = (
    "get_incident",
    "find_runbook",
    "get_relevant_memory",
    *ACTIONS,
    # Orders Platform (MCP)
    "get_source_status",
    "list_upstream_incidents",
)
