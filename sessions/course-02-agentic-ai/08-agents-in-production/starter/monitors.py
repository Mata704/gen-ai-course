"""Exercise 2 — Find the cause in the traces, and watch the agents in production.

Every run of the incident team leaves a trace: OpenTelemetry spans for each agent, model call and tool call.
Tab 2 shows four recorded traces as a waterfall. Something went wrong in three of them. Healthy in one.

You write two things that watch every trace:
1. MONITORS: functions that read a trace and return alerts (a list of short texts; empty = all fine).
   Code, no model: cheap, run on every trace, page someone when they fire.
2. The trace analyst: an agent (a model) that reads describe(trace) and says what went wrong and why.
   describe(trace) is what it sees; ANALYST_INSTRUCTIONS is how it reasons.

The versions below run, but they are naive: the only monitor looks for crashed spans (errors), and the analyst
only sees what the team reported. Run them, read the result, then make them useful.

Goal: on the three problem traces at least one monitor fires; on the healthy trace none does;
and the analyst names the real cause of each problem.

What a trace gives you (lab/traces.py has the details): trace.root (incident, pattern, reported, recovered, gateway),
trace.spans, trace.agents() (model_calls, tool_calls, tokens per agent), trace.tool_calls(), trace.cost_usd().

Hints:
- Read the waterfall of each trace first. What does a problem look like there?
- An agent that fails rarely raises an error: the naive monitor catches one problem out of three. What does "it went wrong" look like in numbers?
- What does the team say happened, and what does the root span say really happened?
- The analyst only knows what describe() shows it.
"""

from __future__ import annotations


def error_spans(trace) -> list[str]:
    """A span that ended with an error (an exception in the code)."""
    return [f"{span['name']} failed: {span['error']}" for span in trace.spans if span["status"] == "ERROR"]


def unrecovered_incident(trace) -> list[str]:
    """The incident is still unhealthy even if an agent reported success."""
    if trace.root.get("recovered") is not False:
        return []
    gateway = trace.root.get("gateway", {})
    return [
        f"Incident not recovered: site {gateway.get('site')}, "
        f"error rate {gateway.get('error_rate')}, latency {gateway.get('latency_ms')} ms."
    ]


def tool_call_spikes(trace) -> list[str]:
    """Flag an agent that exceeded the lab's six-call tool budget."""
    return [
        f"{agent} made {usage['tool_calls']} tool calls (over the six-call budget)."
        for agent, usage in trace.agents().items()
        if usage["tool_calls"] > 6
    ]


def duplicate_specialist_consults(trace) -> list[str]:
    """Flag repeated orchestrator consultations that add cost without new evidence."""
    counts: dict[str, int] = {}
    for call in trace.tool_calls():
        if call["tool"] in {"ask_network", "ask_database"}:
            counts[call["tool"]] = counts.get(call["tool"], 0) + 1
    return [
        f"{tool} was called {count} times."
        for tool, count in counts.items()
        if count > 1
    ]


MONITORS = [error_spans, unrecovered_incident, tool_call_spikes, duplicate_specialist_consults]


ANALYST_INSTRUCTIONS = """\
You analyze production traces from an AI-agent incident team. Do not treat the team's report as proof:
compare it with the root span's recovered flag and gateway metrics.

Explain the actual cause and cite trace evidence. Read each agent's final result alongside relevant tool
arguments/results and span errors. Check whether a cited change ID was passed to remediation and whether
the chosen action matches the findings. Also inspect per-agent model/tool-call and token counts: repeated
specialist consultations or tool-call loops can be the problem even when the incident recovered.

Be concise and distinguish the incident's technical cause, an unsuccessful remediation, and excess cost.
Do not invent details that the trace does not support.
"""


def describe(trace) -> str:
    root = trace.root
    gateway = root.get("gateway", {})
    lines = [
        f"Incident {root.get('incident')}, handled with {root.get('pattern')}.",
        f"Team report: {root.get('reported')}.",
        (
            f"Observed outcome: recovered={root.get('recovered')}; gateway site={gateway.get('site')}, "
            f"latency_ms={gateway.get('latency_ms')}, error_rate={gateway.get('error_rate')}."
        ),
        f"Agent activity (model calls, tool calls, input tokens, output tokens): {trace.agents()}.",
        f"Estimated model cost: ${trace.cost_usd():.5f}.",
    ]

    findings = [
        f"{span['agent']}: {span['attributes']['final_result']}"
        for span in trace.spans
        if span["operation"] == "invoke_agent" and span["attributes"].get("final_result") is not None
    ]
    if findings:
        lines.append("Agent final results: " + " | ".join(findings))

    errors = [f"{span['name']}: {span['error']}" for span in trace.spans if span["status"] == "ERROR"]
    if errors:
        lines.append("Span errors: " + " | ".join(errors))

    evidence = []
    relevant_tools = {"ask_network", "ask_database", "recent_changes", "rollback_change", "failover_gateway", "gateway_state"}
    for call in trace.tool_calls():
        result = str(call["result"])
        if call["tool"] in relevant_tools or '"error"' in result:
            arguments = str(call["arguments"])[:250]
            evidence.append(f"{call['agent']} -> {call['tool']}({arguments}): {result[:350]}")
    if evidence:
        lines.append("Relevant tool evidence: " + " | ".join(evidence))

    return "\n".join(lines)
