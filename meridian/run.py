"""Run one or more harnesses on one or more scenarios.

    uv run python -m meridian.run --harness path/to/harness.py --scenario path/to/case.yaml
    uv run python -m meridian.run --harness a.py --harness b.py --cases-dir path/to/cases --summary

With one harness and one scenario it prints the full trace. With several it
also prints a summary table, so two versions of a harness can be compared on
the same cases. When solutions are available (MERIDIAN_SOLUTIONS or the
trainer's private folder), each run is also evaluated.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from meridian.agent_runtime import IncidentRun, load_harness, print_run, require_api_key, run_incident
from meridian.evaluate import claims_recovery, report_as_dict


def summary_table(runs: list[IncidentRun]) -> None:
    print(f"\n{'scenario':<28} {'harness':<18} {'status':<26} {'tool calls':>10} {'actions':>7} {'evaluation':>10}")
    for run in runs:
        report = report_as_dict(run.report)
        status = run.error and "no report" or str(report.get("status", "?"))
        if report and claims_recovery(report):
            status += " (claims recovery)"
        effects = len(run.sim.executor.effects())
        evaluation = "-" if run.evaluation is None else ("PASS" if run.evaluation.passed else "FAIL")
        print(f"{run.scenario_id:<28} {run.harness:<18} {status:<26} {len(run.trace):>10} {effects:>7} {evaluation:>10}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Meridian incident harnesses.")
    parser.add_argument("--harness", action="append", required=True, help="Harness file (repeat to compare versions).")
    parser.add_argument("--scenario", action="append", default=[], help="Scenario file (repeatable).")
    parser.add_argument("--cases-dir", help="Run every scenario in this folder.")
    parser.add_argument("--summary", action="store_true", help="Only print the summary table.")
    parser.add_argument("--max-requests", type=int, default=20, help="Model request limit per run.")
    args = parser.parse_args()

    scenarios = [Path(path) for path in args.scenario]
    if args.cases_dir:
        scenarios += sorted(Path(args.cases_dir).glob("*.yaml"))
    if not scenarios:
        parser.error("give at least one --scenario or a --cases-dir")

    require_api_key()
    runs = []
    for harness_path in args.harness:
        harness = load_harness(harness_path)
        for scenario in scenarios:
            run = run_incident(harness, scenario, max_requests=args.max_requests)
            runs.append(run)
            if not args.summary:
                print_run(run)
    if len(runs) > 1 or args.summary:
        summary_table(runs)


if __name__ == "__main__":
    main()
