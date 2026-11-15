from __future__ import annotations

import argparse
import sys
from pathlib import Path

from data_quality_agent.persistence.database import DEFAULT_DATABASE
from data_quality_agent.service import PipelineService
from data_quality_agent.simulator.engine import SCENARIOS_DIR


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a synthetic Data Quality pipeline scenario.")
    parser.add_argument(
        "--scenario",
        default=str(SCENARIOS_DIR / "healthy.json"),
        help="Path to a scenario JSON file (defaults to the bundled healthy scenario).",
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="Local JSON array of records. Defaults to the bundled synthetic dataset.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE,
        help="Control database: run history, logs, findings, incidents (defaults to runs/pipelines.sqlite3).",
    )
    parser.add_argument(
        "--warehouse",
        type=Path,
        help="Destination SQLite file for approved data (defaults to warehouse.sqlite3 next to --database).",
    )
    args = parser.parse_args()

    scenario_path = Path(args.scenario)
    try:
        service = PipelineService(database_path=args.database, warehouse_path=args.warehouse)
        result = service.run(scenario_path, input_path=args.input)
    except (OSError, ValueError) as error:
        print(f"Simulation failed: {error}", file=sys.stderr)
        return 2

    print(result.model_dump_json(indent=2))
    return 0
