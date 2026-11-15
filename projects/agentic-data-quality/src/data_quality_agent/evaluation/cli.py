"""Command-line entry point for reproducible Data Quality evaluations."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from data_quality_agent.evaluation import evaluate_cases, load_cases
from data_quality_agent.harness.model import configured_model


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate deterministic pipeline behavior and, optionally, agent trajectories.",
    )
    parser.add_argument(
        "--agents", action="store_true",
        help="Also run the configured model and check incident decisions, required roles, and action traces.",
    )
    parser.add_argument(
        "--scenario", action="append", dest="scenario_ids",
        help="Evaluate only this scenario ID; may be supplied more than once.",
    )
    parser.add_argument(
        "--output", type=Path,
        help="Write the JSON report to this path instead of stdout.",
    )
    parser.add_argument(
        "--workdir", type=Path,
        help="Keep per-case SQLite files in a unique subdirectory here for later inspection.",
    )
    args = parser.parse_args(argv)

    try:
        known = {case.scenario_id for case in load_cases()}
        unknown = set(args.scenario_ids or []) - known
        if unknown:
            parser.error(f"unknown scenario ID(s): {', '.join(sorted(unknown))}")
        report = evaluate_cases(
            with_agents=args.agents,
            model=configured_model() if args.agents else None,
            scenario_ids=args.scenario_ids,
            workdir=args.workdir,
        )
    except (OSError, ValueError) as error:
        print(f"Evaluation could not run: {error}", file=sys.stderr)
        return 2

    report_json = report.model_dump_json(indent=2)
    if args.output is None:
        print(report_json)
    else:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(report_json + "\n", encoding="utf-8")
        except OSError as error:
            print(f"Could not write evaluation report: {error}", file=sys.stderr)
            return 2
        print(f"Evaluation report written to {args.output}")
    return 0 if report.failed_cases == 0 else 1
