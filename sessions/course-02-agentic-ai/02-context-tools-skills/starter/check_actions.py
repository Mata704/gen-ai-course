"""Call a harness's restart tool directly, without a model, and report the effects.

    uv run python sessions/course-02-agentic-ai/02-context-tools-skills/starter/check_actions.py \
        --harness sessions/course-02-agentic-ai/02-context-tools-skills/starter/harness.py

The script calls `restart_instance` from the harness exactly as the model
would, then prints what the executor recorded. It passes `idempotency_key`
only if the tool accepts it.

- same request twice: how many restarts were applied?
- same key, different instance: what does the executor answer?
- lost response (--lost-response): the first answer never arrives; then the
  request is repeated as a model might do.
"""

from __future__ import annotations

import argparse
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from meridian.agent_runtime import IncidentDeps, load_harness
from meridian.scenarios import load_scenario
from meridian.simulator import Simulator
from meridian.tools import MeridianTools

CASE = Path(__file__).resolve().parents[1] / "cases" / "s02-lost-response.yaml"


def call_tool(tool, ctx: Any, target: str, key: str | None) -> dict[str, Any]:
    parameters = list(inspect.signature(tool).parameters)
    kwargs: dict[str, Any] = {parameters[1]: target}
    if key is not None and "idempotency_key" in parameters:
        kwargs["idempotency_key"] = key
    return tool(ctx, **kwargs)


def new_context(lost_response: bool) -> tuple[Simulator, Any]:
    scenario = load_scenario(CASE)
    if not lost_response:
        scenario.executor = {}
    sim = Simulator(scenario)
    return sim, SimpleNamespace(deps=IncidentDeps(MeridianTools(sim)))


def show(title: str, sim: Simulator, results: list[dict[str, Any]]) -> None:
    print(f"\n== {title}")
    for index, result in enumerate(results, start=1):
        print(f"  call {index}: {json.dumps(result)[:160]}")
    restarts = sim.executor.effects("restart_instance")
    print(f"  restarts applied by the executor: {len(restarts)} -> {[record.target for record in restarts]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--harness", required=True)
    parser.add_argument("--lost-response", action="store_true", help="Drop the answer of the first restart.")
    args = parser.parse_args()
    harness = load_harness(args.harness)
    tool = harness.restart_instance

    sim, ctx = new_context(args.lost_response)
    results = [call_tool(tool, ctx, "order-gateway-2", "check-key-1") for _ in range(2)]
    show("same request twice", sim, results)

    sim, ctx = new_context(args.lost_response)
    results = [call_tool(tool, ctx, "order-gateway-2", "check-key-1"), call_tool(tool, ctx, "order-gateway-1", "check-key-1")]
    show("same key, different instance", sim, results)


if __name__ == "__main__":
    main()
