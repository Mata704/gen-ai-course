from __future__ import annotations

import json
import random
import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from data_quality_agent.simulator.destination import (
    DEFAULT_DATABASE,
    DeliveryVerificationError,
    SQLiteDestination,
)
from data_quality_agent.simulator.models import (
    EventKind,
    Fault,
    FaultKind,
    LogLevel,
    PipelineDefinition,
    PipelineEvent,
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

EventListener = Callable[[PipelineEvent], None]
STAGE_ORDER = list(StageName)


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
        on_event: EventListener | None = None,
    ) -> PipelineRun:
        """Run the pipeline; `on_event` receives each progress event as it happens."""
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
        recorder = _RunRecorder(result, stages, on_event)
        try:
            self._execute(scenario, pipeline, result, recorder, input_path)
        except (OSError, ValueError) as error:
            recorder.abort(str(error))
            raise
        recorder.close()
        return result

    def _execute(
        self,
        scenario: Scenario,
        pipeline: PipelineDefinition,
        result: PipelineRun,
        recorder: _RunRecorder,
        input_path: str | Path | None,
    ) -> None:
        recorder.start(StageName.INGESTION)
        recorder.log(f"Scenario '{scenario.scenario_id}': {scenario.description}")
        for fault in scenario.faults:
            if fault.kind == FaultKind.SOURCE_UNAVAILABLE:
                result.errors.append("Synthetic source is unavailable.")
            elif fault.kind == FaultKind.PIPELINE_FAILURE:
                result.errors.append("Synthetic pipeline failure was injected.")

        if result.errors:
            for error in result.errors:
                recorder.log(error, LogLevel.ERROR)
            recorder.finish(StageName.INGESTION, StageStatus.FAILED)
            result.incident = PipelineIncident(
                run_id=result.run_id,
                scenario_id=scenario.scenario_id,
                pipeline_id=pipeline.pipeline_id,
                kind="pipeline_failure",
                summary=" ".join(result.errors),
            )
            self._await_agents(recorder, result.incident)
            return

        source = str(input_path) if input_path is not None else f"bundled dataset '{pipeline.dataset_file}'"
        records = self._load_records(pipeline, scenario.seed, input_path)
        recorder.log(f"Read {len(records)} records from {source}.")
        for fault in scenario.faults:
            if fault.kind in (FaultKind.SOURCE_UNAVAILABLE, FaultKind.PIPELINE_FAILURE):
                continue
            if fault.kind == FaultKind.DELAY:
                result.delay_minutes += self._required(fault.delay_minutes, "delay_minutes", fault)
            else:
                self._apply_data_fault(records, fault)
            recorder.log(f"Injected scenario fault: {_describe_fault(fault)}", LogLevel.WARNING)
        result.input_records = records
        recorder.log(f"Batch contains {len(records)} records after ingestion.")
        recorder.finish(StageName.INGESTION, StageStatus.SUCCEEDED)

        recorder.start(StageName.TRANSFORMATION)
        result.records = self._transform(records)
        result.record_count = len(result.records)
        result.observed_columns = sorted({column for row in result.records for column in row})
        changed = sum(before != after for before, after in zip(records, result.records))
        recorder.log(f"Normalized 'status' in {changed} of {result.record_count} records.")
        recorder.finish(StageName.TRANSFORMATION, StageStatus.SUCCEEDED)

        recorder.start(StageName.DATA_QUALITY)
        recorder.log(
            f"Running {len(pipeline.rules)} deterministic rules on {result.record_count} records."
        )
        result.findings = check_quality(pipeline, result.records, result.delay_minutes)
        failed = {finding.rule_id: finding for finding in result.findings}
        for rule in pipeline.rules:
            finding = failed.get(rule.rule_id)
            if finding is None:
                recorder.log(f"PASS {rule.rule_id}")
            else:
                rows = f" Rows: {finding.row_indexes}." if finding.row_indexes else ""
                recorder.log(f"FAIL {rule.rule_id}: {finding.message}{rows}", LogLevel.ERROR)

        if result.findings:
            result.quality_status = QualityStatus.FAIL
            result.pipeline_status = PipelineStatus.BLOCKED
            recorder.log(
                f"{len(result.findings)} rule(s) failed; delivery is blocked.", LogLevel.ERROR,
            )
            recorder.finish(StageName.DATA_QUALITY, StageStatus.FAILED)
            result.incident = PipelineIncident(
                run_id=result.run_id,
                scenario_id=scenario.scenario_id,
                pipeline_id=pipeline.pipeline_id,
                kind="data_quality",
                summary="Data quality gate failed; agent analysis is pending and delivery is blocked.",
                failed_rule_ids=[finding.rule_id for finding in result.findings],
            )
            self._await_agents(recorder, result.incident)
            return

        result.quality_status = QualityStatus.PASS
        recorder.log("All rules passed.")
        recorder.finish(StageName.DATA_QUALITY, StageStatus.SUCCEEDED)

        recorder.start(StageName.DELIVERY)
        recorder.log(f"Loading {result.record_count} records into {result.destination}.")
        try:
            result.output_records = self.destination.load(
                run_id=result.run_id,
                pipeline_id=pipeline.pipeline_id,
                scenario_id=scenario.scenario_id,
                records=result.records,
            )
        except (sqlite3.Error, OSError, DeliveryVerificationError) as error:
            result.errors.append(f"SQLite delivery failed: {error}")
            recorder.log(result.errors[-1], LogLevel.ERROR)
            recorder.finish(StageName.DELIVERY, StageStatus.FAILED)
            result.incident = PipelineIncident(
                run_id=result.run_id,
                scenario_id=scenario.scenario_id,
                pipeline_id=pipeline.pipeline_id,
                kind="pipeline_failure",
                summary=" ".join(result.errors),
            )
            return
        recorder.log(f"Read back and verified {len(result.output_records)} records.")
        recorder.finish(StageName.DELIVERY, StageStatus.SUCCEEDED)
        result.pipeline_status = PipelineStatus.SUCCEEDED

    @staticmethod
    def _await_agents(recorder: _RunRecorder, incident: PipelineIncident) -> None:
        recorder.start(StageName.AGENT_INTERVENTION)
        recorder.log(f"Incident '{incident.kind}' opened: {incident.summary}", LogLevel.WARNING)
        recorder.log("Waiting for agent intervention (agents are not implemented yet).", LogLevel.WARNING)
        recorder.finish(StageName.AGENT_INTERVENTION, StageStatus.PENDING)

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


class _RunRecorder:
    """Track stage transitions in pipeline order and publish them as events."""

    def __init__(
        self,
        result: PipelineRun,
        stages: dict[StageName, StageResult],
        listener: EventListener | None,
    ) -> None:
        self._result = result
        self._stages = stages
        self._listener = listener
        self._finished: set[StageName] = set()
        self._current: StageName | None = None

    def start(self, stage: StageName) -> None:
        self._finish_earlier(stage)
        self._current = stage
        self._emit(EventKind.STAGE_STARTED, f"Started {stage.value}.", stage=stage)

    def log(self, message: str, level: LogLevel = LogLevel.INFO) -> None:
        self._emit(EventKind.LOG, message, stage=self._current, level=level)

    def finish(self, stage: StageName, status: StageStatus) -> None:
        self._finish_earlier(stage)
        self._stages[stage].status = status
        self._finished.add(stage)
        self._current = None
        self._emit(
            EventKind.STAGE_FINISHED, f"Finished {stage.value}: {status.value}.",
            stage=stage, status=status,
        )

    def abort(self, message: str) -> None:
        """Report an unexpected error in the running stage and close the run."""
        if self._current is not None:
            self.log(message, LogLevel.ERROR)
            self.finish(self._current, StageStatus.FAILED)
        self.close()

    def close(self) -> None:
        for stage in STAGE_ORDER:
            if stage not in self._finished:
                self.finish(stage, self._stages[stage].status)

    def _finish_earlier(self, stage: StageName) -> None:
        for earlier in STAGE_ORDER[:STAGE_ORDER.index(stage)]:
            if earlier not in self._finished:
                self.finish(earlier, self._stages[earlier].status)

    def _emit(
        self,
        kind: EventKind,
        message: str,
        *,
        stage: StageName | None = None,
        status: StageStatus | None = None,
        level: LogLevel = LogLevel.INFO,
    ) -> None:
        event = PipelineEvent(
            sequence=len(self._result.events),
            run_id=self._result.run_id,
            timestamp=datetime.now(timezone.utc),
            kind=kind,
            stage=stage,
            status=status,
            level=level,
            message=message,
        )
        self._result.events.append(event)
        if self._listener is not None:
            self._listener(event)


def _describe_fault(fault: Fault) -> str:
    details = fault.model_dump(exclude={"kind"}, exclude_none=True)
    if not details:
        return fault.kind.value
    return f"{fault.kind.value} " + ", ".join(f"{key}={value!r}" for key, value in details.items())
