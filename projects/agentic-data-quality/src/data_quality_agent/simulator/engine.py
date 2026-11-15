from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

from data_quality_agent.simulator.destination import (
    DEFAULT_WAREHOUSE,
    DeliveryVerificationError,
    SQLiteDestination,
)
from data_quality_agent.simulator.events import EventListener, RunRecorder
from data_quality_agent.simulator.input_data import (
    DATASETS_DIR as DATASETS_DIR,
    apply_data_fault,
    describe_fault,
    load_records,
    required_fault_value,
    transform,
)
from data_quality_agent.simulator.models import (
    FaultKind,
    LogLevel,
    PipelineConfig,
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
from data_quality_agent.simulator.rule_library import load_general_rules, resolve_pipeline

SIMULATOR_DIR = Path(__file__).parent
PIPELINES_DIR = SIMULATOR_DIR / "definitions"
SCENARIOS_DIR = SIMULATOR_DIR / "scenarios"


def load_scenario(path: str | Path) -> Scenario:
    scenario_path = Path(path)
    return Scenario.model_validate_json(scenario_path.read_text(encoding="utf-8"))


def load_pipeline(pipeline_id: str) -> PipelineDefinition:
    """The pipeline file resolved against the general rules, so it holds its effective rules."""
    path = PIPELINES_DIR / f"{pipeline_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Unknown pipeline definition: {pipeline_id}")
    config = PipelineConfig.model_validate_json(path.read_text(encoding="utf-8"))
    return resolve_pipeline(config, load_general_rules())


class PipelineSimulator:
    """Simulate ingestion, transformation, a quality gate and SQLite delivery."""

    def __init__(self, warehouse_path: str | Path = DEFAULT_WAREHOUSE) -> None:
        self.destination = SQLiteDestination(warehouse_path)

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
        recorder = RunRecorder(result, stages, on_event)
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
        recorder: RunRecorder,
        input_path: str | Path | None,
    ) -> None:
        recorder.start(StageName.INGESTION)
        recorder.log(
            f"Scenario '{scenario.scenario_id}': {scenario.description}", simulation_only=True,
        )
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
        records = load_records(pipeline, scenario.seed, input_path)
        recorder.log(f"Read {len(records)} records from {source}.")
        for fault in scenario.faults:
            if fault.kind in (FaultKind.SOURCE_UNAVAILABLE, FaultKind.PIPELINE_FAILURE):
                continue
            if fault.kind == FaultKind.DELAY:
                result.delay_minutes += required_fault_value(fault.delay_minutes, "delay_minutes", fault)
            else:
                apply_data_fault(records, fault)
            recorder.log(
                f"Injected scenario fault: {describe_fault(fault)}", LogLevel.WARNING,
                simulation_only=True,
            )
        result.input_records = records
        recorder.log(f"Batch contains {len(records)} records after ingestion.")
        recorder.finish(StageName.INGESTION, StageStatus.SUCCEEDED)

        recorder.start(StageName.TRANSFORMATION)
        result.records = transform(records)
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
    def _await_agents(recorder: RunRecorder, incident: PipelineIncident) -> None:
        recorder.start(StageName.AGENT_INTERVENTION)
        recorder.log(f"Incident '{incident.kind}' opened: {incident.summary}", LogLevel.WARNING)
        recorder.log("Waiting for agent intervention (agents are not implemented yet).", LogLevel.WARNING)
        recorder.finish(StageName.AGENT_INTERVENTION, StageStatus.PENDING)
