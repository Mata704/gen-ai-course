"""Application service: run a pipeline, keep its history in the control database and deliver
approved data to the separate destination (warehouse) file."""

from __future__ import annotations

from pathlib import Path

from data_quality_agent.persistence.database import DEFAULT_DATABASE, Database
from data_quality_agent.persistence.repository import RunRepository
from data_quality_agent.simulator.engine import (
    EventListener,
    PipelineSimulator,
    load_pipeline,
    load_scenario,
)
from data_quality_agent.simulator.models import PipelineEvent, PipelineRun, Scenario

WAREHOUSE_FILENAME = "warehouse.sqlite3"


class PipelineService:
    """Used by the CLI and the UI, so every run is persisted the same way."""

    def __init__(
        self, database_path: str | Path = DEFAULT_DATABASE, warehouse_path: str | Path | None = None,
    ) -> None:
        self.database = Database(database_path)
        self.runs = RunRepository(self.database)
        # By default the warehouse sits next to the control database (runs/warehouse.sqlite3).
        if warehouse_path is None:
            warehouse_path = self.database.path.parent / WAREHOUSE_FILENAME
        self.simulator = PipelineSimulator(warehouse_path=warehouse_path)

    def run(
        self,
        scenario: Scenario | str | Path,
        *,
        input_path: str | Path | None = None,
        on_event: EventListener | None = None,
    ) -> PipelineRun:
        if isinstance(scenario, (str, Path)):
            scenario = load_scenario(scenario)
        pipeline = load_pipeline(scenario.pipeline_id)
        version = self.runs.register_pipeline(pipeline)
        started: list[str] = []

        def persist(event: PipelineEvent) -> None:
            # Events are written as they happen, so other processes can follow a run in progress.
            if not started:
                self.runs.start_run(
                    run_id=event.run_id,
                    pipeline_id=pipeline.pipeline_id,
                    pipeline_version=version,
                    scenario_id=scenario.scenario_id,
                    seed=scenario.seed,
                    destination=str(self.simulator.destination.path.resolve()),
                    started_at=event.timestamp,
                )
                started.append(event.run_id)
            self.runs.append_event(event)
            if on_event is not None:
                on_event(event)

        try:
            result = self.simulator.run(scenario, input_path=input_path, on_event=persist)
        except (OSError, ValueError) as error:
            if started:
                self.runs.fail_run(started[0], str(error))
            raise
        self.runs.finish_run(result)
        return result
