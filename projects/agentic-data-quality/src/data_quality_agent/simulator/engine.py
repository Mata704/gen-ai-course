from __future__ import annotations

import json
import random
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

from data_quality_agent.simulator.destination import (
    DEFAULT_DATABASE,
    DeliveryVerificationError,
    SQLiteDestination,
)
from data_quality_agent.simulator.models import (
    Fault,
    FaultKind,
    PipelineDefinition,
    PipelineIncident,
    PipelineRun,
    PipelineStatus,
    QualityStatus,
    Scenario,
    StageName,
    StageResult,
    StageStatus,
)
from data_quality_agent.simulator.quality import check_quality

SIMULATOR_DIR = Path(__file__).parent
PIPELINES_DIR = SIMULATOR_DIR / "definitions"
DATASETS_DIR = SIMULATOR_DIR / "datasets"
SCENARIOS_DIR = SIMULATOR_DIR / "scenarios"


def load_scenario(path: str | Path) -> Scenario:
    scenario_path = Path(path)
    return Scenario.model_validate_json(scenario_path.read_text(encoding="utf-8"))


def load_pipeline(pipeline_id: str) -> PipelineDefinition:
    path = PIPELINES_DIR / f"{pipeline_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Unknown pipeline definition: {pipeline_id}")
    return PipelineDefinition.model_validate_json(path.read_text(encoding="utf-8"))


class PipelineSimulator:
    """Simulate ingestion, transformation, a quality gate and SQLite delivery."""

    def __init__(self, database_path: str | Path = DEFAULT_DATABASE) -> None:
        self.destination = SQLiteDestination(database_path)

    def run(
        self,
        scenario: Scenario | str | Path,
        *,
        input_path: str | Path | None = None,
    ) -> PipelineRun:
        if isinstance(scenario, (str, Path)):
            scenario = load_scenario(scenario)

        pipeline = load_pipeline(scenario.pipeline_id)
        stages = {name: StageResult(name=name, status=StageStatus.SKIPPED) for name in StageName}
        result = PipelineRun(
            run_id=str(uuid4()),
            scenario_id=scenario.scenario_id,
            pipeline_id=pipeline.pipeline_id,
            seed=scenario.seed,
            pipeline_status=PipelineStatus.FAILED,
            quality_status=QualityStatus.NOT_RUN,
            record_count=0,
            delay_minutes=0,
            observed_columns=[],
            stages=list(stages.values()),
            destination=str(self.destination.path.resolve()),
        )

        for fault in scenario.faults:
            if fault.kind == FaultKind.SOURCE_UNAVAILABLE:
                result.errors.append("Synthetic source is unavailable.")
            elif fault.kind == FaultKind.PIPELINE_FAILURE:
                result.errors.append("Synthetic pipeline failure was injected.")

        if result.errors:
            stages[StageName.INGESTION].status = StageStatus.FAILED
            stages[StageName.AGENT_INTERVENTION].status = StageStatus.PENDING
            result.incident = PipelineIncident(
                run_id=result.run_id,
                scenario_id=scenario.scenario_id,
                pipeline_id=pipeline.pipeline_id,
                kind="pipeline_failure",
                summary=" ".join(result.errors),
            )
            return result

        records = self._load_records(pipeline, scenario.seed, input_path)
        for fault in scenario.faults:
            if fault.kind in (FaultKind.SOURCE_UNAVAILABLE, FaultKind.PIPELINE_FAILURE):
                continue
            if fault.kind == FaultKind.DELAY:
                result.delay_minutes += self._required(fault.delay_minutes, "delay_minutes", fault)
            else:
                self._apply_data_fault(records, fault)
        result.input_records = records
        stages[StageName.INGESTION].status = StageStatus.SUCCEEDED

        result.records = self._transform(records)
        result.record_count = len(result.records)
        result.observed_columns = sorted({column for row in result.records for column in row})
        stages[StageName.TRANSFORMATION].status = StageStatus.SUCCEEDED

        result.findings = check_quality(pipeline, result.records, result.delay_minutes)
        if result.findings:
            result.quality_status = QualityStatus.FAIL
            result.pipeline_status = PipelineStatus.BLOCKED
            stages[StageName.DATA_QUALITY].status = StageStatus.FAILED
            stages[StageName.AGENT_INTERVENTION].status = StageStatus.PENDING
            result.incident = PipelineIncident(
                run_id=result.run_id,
                scenario_id=scenario.scenario_id,
                pipeline_id=pipeline.pipeline_id,
                kind="data_quality",
                summary="Data quality gate failed; agent analysis is pending and delivery is blocked.",
                failed_rule_ids=[finding.rule_id for finding in result.findings],
            )
            return result

        result.quality_status = QualityStatus.PASS
        stages[StageName.DATA_QUALITY].status = StageStatus.SUCCEEDED
        try:
            result.output_records = self.destination.load(
                run_id=result.run_id,
                pipeline_id=pipeline.pipeline_id,
                scenario_id=scenario.scenario_id,
                records=result.records,
            )
        except (sqlite3.Error, OSError, DeliveryVerificationError) as error:
            result.errors.append(f"SQLite delivery failed: {error}")
            stages[StageName.DELIVERY].status = StageStatus.FAILED
            result.incident = PipelineIncident(
                run_id=result.run_id,
                scenario_id=scenario.scenario_id,
                pipeline_id=pipeline.pipeline_id,
                kind="pipeline_failure",
                summary=" ".join(result.errors),
            )
            return result
        stages[StageName.DELIVERY].status = StageStatus.SUCCEEDED
        result.pipeline_status = PipelineStatus.SUCCEEDED
        return result

    @staticmethod
    def _load_records(
        pipeline: PipelineDefinition,
        seed: int,
        input_path: str | Path | None,
    ) -> list[dict[str, Any]]:
        if input_path is not None:
            path = Path(input_path)
        else:
            filename = Path(pipeline.dataset_file)
            if filename.name != pipeline.dataset_file:
                raise ValueError("Dataset file must be a filename inside the simulator dataset directory.")
            path = DATASETS_DIR / filename
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
            raise ValueError(f"Input dataset must contain a JSON array of records: {path}")
        records = [dict(row) for row in payload]
        if input_path is None:
            random.Random(seed).shuffle(records)
        return records

    @staticmethod
    def _transform(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        transformed = []
        for record in records:
            row = dict(record)
            if isinstance(row.get("status"), str):
                row["status"] = row["status"].strip().lower()
            transformed.append(row)
        return transformed

    @staticmethod
    def _required(value: Any, name: str, fault: Fault) -> Any:
        if value is None:
            raise ValueError(f"Fault '{fault.kind}' requires '{name}'.")
        return value

    def _apply_data_fault(self, records: list[dict[str, Any]], fault: Fault) -> None:
        if fault.kind == FaultKind.DROP_ROWS:
            count = self._required(fault.count, "count", fault)
            if count > len(records):
                raise ValueError("drop_rows count exceeds the number of records.")
            del records[-count:]
            return

        if fault.kind in (FaultKind.DUPLICATE_ROW, FaultKind.NULL_VALUE, FaultKind.SET_VALUE):
            row_index = self._required(fault.row_index, "row_index", fault)
            if row_index >= len(records):
                raise ValueError(f"row_index {row_index} is outside the current dataset.")
            if fault.kind == FaultKind.DUPLICATE_ROW:
                records.append(dict(records[row_index]))
                return

            field = self._required(fault.field, "field", fault)
            records[row_index][field] = None if fault.kind == FaultKind.NULL_VALUE else fault.value
            return

        if fault.kind in (FaultKind.DROP_COLUMN, FaultKind.ADD_COLUMN):
            field = self._required(fault.field, "field", fault)
            if fault.kind == FaultKind.DROP_COLUMN:
                for row in records:
                    row.pop(field, None)
            else:
                for row in records:
                    row[field] = fault.value
