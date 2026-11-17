"""The agent harness: everything that shapes what the agents do, in one place.

An agent is a model plus a harness: its instructions, its tools, the format of its answer and the
checks around it (course session 01). Each file below holds one of those parts:

    orchestrator.py   coordinator: instructions, final answer, delegation and the check of its answer
    investigation.py combined quality and pipeline investigation: instructions and tools
    remediation.py    remediation specialist: instructions, tools and the two automatic actions
    recovery.py       deterministic quality and delivery verification (not an agent)
    specialists.py    what every specialist is told, its answer format and the shared checks
    hooks.py          code run before and after every tool call (allowlist, budget, size, trust)
    policies.py       when an automatic action may run (decided in code, never by the model)
    model.py          which model is used (the course OpenAI configuration)
    team.py           wires the pieces together; you do not need to edit it to change behavior

Agents never receive batch records: their tools return rules, counts, row positions, logs and refs.
"""

from data_quality_agent.harness import investigation, remediation

SPECIALISTS = {module.ROLE: module for module in (investigation, remediation)}
# Least privilege: the tool catalog grants each tool only to the roles that list it here.
TOOLS_BY_ROLE: dict[str, tuple[str, ...]] = {role: module.TOOLS for role, module in SPECIALISTS.items()}

__all__ = ["SPECIALISTS", "TOOLS_BY_ROLE"]
