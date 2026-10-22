"""Checks for the simulator itself. Run with: uv run python -m pytest meridian/tests"""

from __future__ import annotations

from pathlib import Path

import pytest

from meridian import MeridianTools, Simulator, load_scenario
from meridian.evaluate import evaluate

REPO = Path(__file__).resolve().parents[2]
S1 = REPO / "sessions" / "course-02-agentic-ai" / "01-agent-harness" / "cases"
S2 = REPO / "sessions" / "course-02-agentic-ai" / "02-context-tools-skills" / "cases"
ALL_CASES = sorted(S1.glob("*.yaml")) + sorted(S2.glob("*.yaml"))


@pytest.mark.parametrize("path", ALL_CASES, ids=lambda path: path.stem)
def test_every_case_loads_and_opens_its_alert(path: Path) -> None:
    sim = Simulator(path)
    brief = sim.incident_brief()
    assert brief["alert_id"] is not None
    assert sim.state.tick == sim.scenario.warmup_ticks


def test_same_seed_gives_same_signals() -> None:
    first = Simulator(S2 / "s02-noisy-gateway.yaml")
    second = Simulator(S2 / "s02-noisy-gateway.yaml")
    assert first.logs.lines == second.logs.lines
    assert first.metrics.history == second.metrics.history


def test_memory_leak_raises_latency_and_restart_only_helps_for_a_while() -> None:
    sim = Simulator(S1 / "s01-gateway-latency.yaml")
    tools = MeridianTools(sim)
    assert sim.state.component("order-gateway").latency_ms > 100
    tools.restart_instance("order-gateway-2")
    sim.advance(3)
    assert sim.state.component("order-gateway").latency_ms < 20
    sim.advance(130)
    assert sim.state.component("order-gateway").latency_ms > 100


def test_each_tool_call_moves_time_by_a_fixed_step() -> None:
    sim = Simulator(S1 / "s01-gateway-latency.yaml")
    tools = MeridianTools(sim)
    start = sim.state.tick
    tools.read_metrics("order-gateway")
    tools.read_metrics("order-gateway")
    assert sim.state.tick == start + 2 * sim.scenario.ticks_per_action
    assert [call.tick for call in tools.trace] == [start, start + 1]


def test_idempotency_key_prevents_a_second_effect_and_detects_conflicts() -> None:
    scenario = load_scenario(S2 / "s02-lost-response.yaml")
    scenario.executor = {}
    sim = Simulator(scenario)
    tools = MeridianTools(sim)
    assert tools.restart_instance("order-gateway-2", idempotency_key="k")["status"] == "completed"
    assert tools.restart_instance("order-gateway-2", idempotency_key="k")["status"] == "already_applied"
    assert tools.restart_instance("order-gateway-1", idempotency_key="k")["status"] == "conflict"
    assert len(sim.executor.effects("restart_instance")) == 1


def test_lost_response_applies_the_effect_and_reports_a_timeout() -> None:
    sim = Simulator(S2 / "s02-lost-response.yaml")
    tools = MeridianTools(sim)
    result = tools.restart_instance("order-gateway-2", idempotency_key="k")
    assert "timeout" in result["error"]
    assert tools.action_status("k")["status"] == "completed"
    assert len(sim.executor.effects("restart_instance", "order-gateway-2")) == 1


def test_critical_components_need_an_approval() -> None:
    sim = Simulator(S2 / "s02-hidden-config-change.yaml")
    tools = MeridianTools(sim)
    assert tools.rollback_change("CHG-4471")["status"] == "rejected"
    assert tools.restart_service("matching-engine")["status"] == "rejected"


def test_rolling_back_the_change_removes_its_effects() -> None:
    scenario = load_scenario(S2 / "s02-hidden-config-change.yaml")
    scenario.approvals = ["APR-1"]
    sim = Simulator(scenario)
    tools = MeridianTools(sim)
    assert sim.state.component("order-gateway").error_rate > 0.2
    assert tools.rollback_change("CHG-4471", confirmation_ref="APR-1")["status"] == "completed"
    sim.advance(1)
    assert sim.state.component("order-gateway").error_rate < 0.01


def test_hidden_clue_is_a_single_reference_db_line() -> None:
    sim = Simulator(S2 / "s02-hidden-config-change.yaml")
    matches = [line for line in sim.logs.lines if "CHG-4471" in line["message"]]
    assert len(matches) == 1 and matches[0]["component"] == "reference-db"
    assert len(sim.logs.lines) > 4000


def test_evaluation_checks_claims_reads_and_effects() -> None:
    sim = Simulator(S1 / "s01-gateway-latency.yaml")
    tools = MeridianTools(sim)
    tools.read_alert(sim.incident_brief()["alert_id"])
    key = {
        "report": {"claims_recovery": False},
        "required_reads": [{"tool": "read_metrics", "component": "order-gateway"}],
        "forbidden_actions": [{"action": "restart_service", "target": "order-gateway"}],
    }
    result = evaluate(sim, tools.trace, {"status": "resolved"}, key)
    assert not result.passed
    assert [check.passed for check in result.checks] == [False, False, True]
