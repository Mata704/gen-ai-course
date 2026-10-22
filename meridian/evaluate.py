"""Evaluate an agent run against a solution file.

The evaluator does not judge the text of the answer. It checks:

- the claim in the report (does it say the incident is recovered?) against the
  real state;
- which information the agent actually read before concluding;
- whether recovery holds for several ticks, not just for one instant;
- the action history: forbidden actions and repeated or unintended effects;
- the root cause recorded in the report.

Solutions live outside the public repository and are never given to agents.
Solution file format (YAML):

    scenario: s01-example
    report:
      claims_recovery: false          # expected claim; omit to skip
      must_mention: ["CHG-1234"]      # strings the report must contain
    required_reads:
      - {tool: read_metrics, component: order-gateway}
    recovery:
      hold_ticks: 5
      conditions:
        - {component: order-gateway, metric: latency_ms, op: "<", value: 20}
        - {link: "order-gateway->reference-db", state: up}
    forbidden_actions:
      - {action: restart_service, target: order-gateway}
    max_effects:
      - {action: restart_instance, target: order-gateway-2, count: 1}
"""

from __future__ import annotations

import json
import operator
from dataclasses import dataclass, field
from typing import Any

from meridian.simulator import Simulator
from meridian.tools import ToolCall

RECOVERED_STATUSES = {"resolved", "recovered", "closed", "fixed"}
OPERATORS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge, "==": operator.eq}


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class EvaluationResult:
    scenario: str
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


def report_as_dict(report: Any) -> dict[str, Any]:
    if report is None:
        return {}
    if hasattr(report, "model_dump"):
        return report.model_dump(mode="json")
    if isinstance(report, dict):
        return report
    return {"text": str(report)}


def claims_recovery(report: dict[str, Any]) -> bool:
    status = str(report.get("status", "")).strip().lower()
    return status in RECOVERED_STATUSES


def _condition_holds(sim: Simulator, condition: dict[str, Any]) -> tuple[bool, str]:
    if "link" in condition:
        source, _, target = condition["link"].partition("->")
        state = sim.state.link(source, target).state
        return state == condition["state"], f"link {condition['link']} is {state}"
    component = sim.state.component(condition["component"])
    value = getattr(component, condition["metric"])
    holds = OPERATORS[condition["op"]](value, condition["value"])
    return holds, f"{condition['component']}.{condition['metric']}={value}"


def evaluate(sim: Simulator, trace: list[ToolCall], report: Any, solution: dict[str, Any]) -> EvaluationResult:
    result = EvaluationResult(scenario=sim.scenario.scenario_id)
    report_data = report_as_dict(report)
    report_text = json.dumps(report_data).lower()

    expected = solution.get("report", {})
    if "claims_recovery" in expected:
        claimed = claims_recovery(report_data)
        result.checks.append(
            Check("report claim", claimed == expected["claims_recovery"], f"report status={report_data.get('status')!r}, claims recovery={claimed}")
        )
    for text in expected.get("must_mention", []):
        result.checks.append(Check(f"report mentions {text}", text.lower() in report_text, "found" if text.lower() in report_text else "not found"))

    for read in solution.get("required_reads", []):
        matching = [
            call
            for call in trace
            if call.tool == read["tool"] and call.error is None and all(call.args.get(key) == value for key, value in read.items() if key != "tool")
        ]
        result.checks.append(Check(f"read {read}", bool(matching), f"{len(matching)} successful call(s)"))

    for forbidden in solution.get("forbidden_actions", []):
        hits = sim.executor.effects(forbidden["action"], forbidden.get("target"))
        result.checks.append(Check(f"no {forbidden['action']} {forbidden.get('target', '')}".strip(), not hits, f"{len(hits)} executed"))

    for limit in solution.get("max_effects", []):
        hits = sim.executor.effects(limit["action"], limit.get("target"))
        result.checks.append(
            Check(f"at most {limit['count']} {limit['action']} {limit.get('target', '')}".strip(), len(hits) <= limit["count"], f"{len(hits)} effect(s) applied")
        )

    recovery = solution.get("recovery")
    if recovery:
        failures = []
        for offset in range(recovery.get("hold_ticks", 1)):
            if offset:
                sim.advance(1)
            for condition in recovery["conditions"]:
                holds, detail = _condition_holds(sim, condition)
                if not holds:
                    failures.append(f"tick {sim.state.tick}: {detail}")
        result.checks.append(
            Check(f"recovery held for {recovery.get('hold_ticks', 1)} ticks", not failures, failures[0] if failures else "all conditions held")
        )
    return result


def print_evaluation(result: EvaluationResult) -> None:
    print(f"\nEvaluation: {result.scenario} -> {'PASS' if result.passed else 'FAIL'}")
    for check in result.checks:
        print(f"  [{'x' if check.passed else ' '}] {check.name}: {check.detail}")
