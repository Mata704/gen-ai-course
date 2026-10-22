"""Run a PydanticAI agent on a Meridian scenario and show what happened.

A harness is a Python file that defines `build_agent(model) -> Agent`. It may
also define `build_prompt(brief, deps) -> str` to control the first message
(`deps` gives access to the tools and the simulator).
Sessions keep their harness files next to their exercises; this module only
provides the plumbing to load a harness, run it and print the trace.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from dotenv import load_dotenv
from pydantic_ai import capture_run_messages
from pydantic_ai.exceptions import AgentRunError, UsageLimitExceeded
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, RetryPromptPart, ToolCallPart, ToolReturnPart
from pydantic_ai.usage import UsageLimits

from meridian.evaluate import EvaluationResult, evaluate, print_evaluation, report_as_dict
from meridian.scenarios import load_solution, load_scenario
from meridian.simulator import Simulator
from meridian.tools import MeridianTools, ToolCall

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOLUTIONS_DIR = REPO_ROOT / "private" / "course-02-agentic-ai" / "solutions"


@dataclass
class IncidentDeps:
    """Dependencies available to tools through `RunContext.deps`."""

    tools: MeridianTools

    @property
    def sim(self) -> Simulator:
        return self.tools.sim


@dataclass
class IncidentRun:
    scenario_id: str
    harness: str
    brief: dict[str, Any]
    report: Any
    trace: list[ToolCall]
    sim: Simulator
    error: str | None = None
    messages: list[ModelMessage] = field(default_factory=list)
    evaluation: EvaluationResult | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def default_model() -> str:
    load_dotenv()
    return f"openai:{os.getenv('OPENAI_MODEL', 'gpt-4.1-mini')}"


def require_api_key() -> None:
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is missing. Create a local .env from .env.example.")


def load_harness(path: str | Path) -> ModuleType:
    path = Path(path).resolve()
    module_name = f"harness_{path.stem}_{abs(hash(path)) % 10_000}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Cannot load harness from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    if not hasattr(module, "build_agent"):
        raise SystemExit(f"{path} must define build_agent(model)")
    return module


def default_prompt(brief: dict[str, Any], deps: IncidentDeps | None = None) -> str:
    alert = f" Related alert: {brief['alert_id']}." if brief.get("alert_id") else ""
    return f"Incident {brief['incident_id']} ({brief['time']}): {brief['summary']}{alert}"


def find_solution(scenario_id: str, solutions_dir: Path | None = None) -> Path | None:
    directory = solutions_dir or Path(os.getenv("MERIDIAN_SOLUTIONS", DEFAULT_SOLUTIONS_DIR))
    path = directory / f"{scenario_id}.yaml"
    return path if path.is_file() else None


def run_incident(
    harness: ModuleType,
    scenario_path: str | Path,
    *,
    model: Any = None,
    max_requests: int = 20,
    solutions_dir: Path | None = None,
) -> IncidentRun:
    """Run one harness on one scenario. Evaluate it when a solution file exists."""
    scenario = load_scenario(scenario_path)
    sim = Simulator(scenario)
    tools = MeridianTools(sim)
    agent = harness.build_agent(model or default_model())
    brief = sim.incident_brief()
    build_prompt: Callable[[dict[str, Any], IncidentDeps], str] = getattr(harness, "build_prompt", default_prompt)
    deps = IncidentDeps(tools)

    report, error = None, None
    with capture_run_messages() as messages:
        try:
            result = agent.run_sync(build_prompt(brief, deps), deps=deps, usage_limits=UsageLimits(request_limit=max_requests))
            report = result.output
        except UsageLimitExceeded as exceeded:
            error = f"stopped: {exceeded}"
        except AgentRunError as failure:
            error = f"agent error: {failure}"

    run = IncidentRun(scenario.scenario_id, Path(harness.__file__).name, brief, report, tools.trace, sim, error, list(messages))
    run.extra["end_tick"] = sim.state.tick
    solution_path = find_solution(scenario.scenario_id, solutions_dir)
    if solution_path is not None:
        run.evaluation = evaluate(sim, tools.trace, report, load_solution(solution_path))
    return run


def _short(value: Any, width: int = 110) -> str:
    text = json.dumps(value, default=str)
    return text if len(text) <= width else text[: width - 3] + "..."


def model_trace(messages: list[ModelMessage]) -> list[tuple[str, str]]:
    """What the model asked for and what it received, in order."""
    lines: list[tuple[str, str]] = []
    for message in messages:
        for part in message.parts:
            if isinstance(message, ModelResponse) and isinstance(part, ToolCallPart):
                lines.append(("call", f"{part.tool_name}({_short(part.args_as_dict(), 70)})"))
            elif isinstance(message, ModelRequest) and isinstance(part, ToolReturnPart):
                lines.append(("result", _short(part.content)))
            elif isinstance(message, ModelRequest) and isinstance(part, RetryPromptPart):
                lines.append(("retry", _short(part.content)))
    return lines


def print_run(run: IncidentRun, show_trace: bool = True) -> None:
    print(f"\n=== {run.scenario_id} | harness {run.harness} | incident {run.brief['incident_id']} ===")
    if show_trace:
        print("What the model requested and received:")
        steps = model_trace(run.messages)
        step = 0
        for kind, text in steps:
            if kind == "call":
                step += 1
                print(f"{step:>4}  {text}")
            else:
                print(f"      {'->' if kind == 'result' else 'retry:'} {text}")
        if not steps:
            print("      (no tool calls)")
        print(f"Simulated time: {run.sim.clock.label(run.brief['tick'])} -> {run.sim.clock.label(run.extra.get('end_tick', run.sim.state.tick))}")
    if run.error:
        print(f"Run ended without a report: {run.error}")
    else:
        print("Report:")
        print(json.dumps(report_as_dict(run.report), indent=2, default=str))
    actions = [record for record in run.sim.executor.audit]
    if actions:
        print("Actions recorded by the executor:")
        for record in actions:
            print(f"  {record.action_id} {record.time} {record.action} {record.target} -> {record.outcome}")
    if run.evaluation is not None:
        print_evaluation(run.evaluation)
