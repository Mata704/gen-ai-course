"""mrx-chaos: run a scenario without an agent and watch the symptoms.

    mrx-chaos show <scenario.yaml>
    mrx-chaos run <scenario.yaml> [--ticks 20] [--component order-gateway]

`run` prints one line per tick (latency, error rate, queue, open alerts), so
you can see how a fault propagates before any agent touches the system.
"""

from __future__ import annotations

import argparse

from meridian.scenarios import load_scenario
from meridian.simulator import Simulator


def show(path: str) -> None:
    scenario = load_scenario(path)
    print(f"{scenario.scenario_id}: {scenario.title}")
    print(f"Incident {scenario.incident['id']}: {scenario.incident['summary']}")
    print(f"Starts at {scenario.start_time} after {scenario.warmup_ticks} warm-up ticks; seed {scenario.seed}.")


def run(path: str, ticks: int, component: str) -> None:
    sim = Simulator(path)
    brief = sim.incident_brief()
    print(f"{sim.scenario.scenario_id} | incident {brief['incident_id']} | alert {brief['alert_id']}")
    print(f"{'tick':>4} {'time':>5} {'latency_ms':>10} {'error_rate':>10} {'queue':>7} {'open_alerts':>11} trading")
    for offset in range(ticks + 1):
        if offset:
            sim.advance(1)
        values = sim.snapshot()["components"][component]
        open_alerts = sum(1 for alert in sim.alerts.alerts if alert.state == "open")
        trading = "yes" if sim.clock.is_trading_session(sim.state.tick) else "no"
        print(
            f"{sim.state.tick:>4} {sim.clock.label(sim.state.tick):>5} {values['latency_ms']:>10} "
            f"{values['error_rate']:>10} {values['queue_depth']:>7} {open_alerts:>11} {trading}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(prog="mrx-chaos", description="Run Meridian Exchange scenarios without an agent.")
    commands = parser.add_subparsers(dest="command", required=True)
    show_parser = commands.add_parser("show", help="Describe a scenario.")
    show_parser.add_argument("scenario")
    run_parser = commands.add_parser("run", help="Simulate a scenario tick by tick.")
    run_parser.add_argument("scenario")
    run_parser.add_argument("--ticks", type=int, default=20)
    run_parser.add_argument("--component", default="order-gateway")
    args = parser.parse_args()
    if args.command == "show":
        show(args.scenario)
    else:
        run(args.scenario, args.ticks, args.component)


if __name__ == "__main__":
    main()
