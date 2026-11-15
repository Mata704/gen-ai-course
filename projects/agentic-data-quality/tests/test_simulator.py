import json
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import pytest

from data_quality_agent.simulator.cli import main
from data_quality_agent.simulator.destination import SQLiteDestination
from data_quality_agent.simulator.engine import DATASETS_DIR, PipelineSimulator, SCENARIOS_DIR, load_pipeline
from data_quality_agent.simulator.models import (
    EventKind,
    LogLevel,
    PipelineEvent,
    PipelineStatus,
    QualityStatus,
    StageName,
    StageStatus,
)
from data_quality_agent.simulator.quality import check_quality


@pytest.fixture
def simulator(tmp_path: Path) -> PipelineSimulator:
    return PipelineSimulator(database_path=tmp_path / "output.sqlite3")


@pytest.fixture
def input_path(tmp_path: Path) -> Path:
    path = tmp_path / "incoming orders.json"
    path.write_text((DATASETS_DIR / "orders.json").read_text(encoding="utf-8"), encoding="utf-8")
    return path


def test_healthy_scenario_passes_data_quality_checks(simulator: PipelineSimulator) -> None:
    result = simulator.run(SCENARIOS_DIR / "healthy.json")

    assert result.pipeline_status == PipelineStatus.SUCCEEDED
    assert result.quality_status == QualityStatus.PASS
    assert result.record_count == 5
    assert result.findings == []
    assert [stage.name for stage in result.stages] == [
        StageName.INGESTION, StageName.TRANSFORMATION, StageName.DATA_QUALITY,
        StageName.AGENT_INTERVENTION, StageName.REVALIDATION, StageName.DELIVERY,
    ]
    assert [stage.status for stage in result.stages] == [
        StageStatus.SUCCEEDED, StageStatus.SUCCEEDED, StageStatus.SUCCEEDED,
        StageStatus.SKIPPED, StageStatus.SKIPPED, StageStatus.SUCCEEDED,
    ]
    assert result.output_records == result.records
    assert result.incident is None
    with closing(sqlite3.connect(result.destination)) as connection:
        rows = connection.execute(
            "SELECT record_json FROM pipeline_output WHERE run_id = ? ORDER BY position",
            (result.run_id,),
        ).fetchall()
    assert [json.loads(row[0]) for row in rows] == result.output_records


def test_quality_scenario_identifies_each_row_level_defect(simulator: PipelineSimulator) -> None:
    with patch.object(SQLiteDestination, "load") as deliver:
        result = simulator.run(SCENARIOS_DIR / "quality_issues.json")
        deliver.assert_not_called()

    assert result.pipeline_status == PipelineStatus.BLOCKED
    assert result.quality_status == QualityStatus.FAIL
    assert {finding.rule_id for finding in result.findings} == {
        "required-customer",
        "unique-order",
        "valid-amount",
        "valid-status",
        "known-customer",
    }
    assert all(finding.row_indexes for finding in result.findings)
    assert result.output_records == []
    assert result.stages[-1].status == StageStatus.SKIPPED
    assert result.incident is not None
    assert result.incident.kind == "data_quality"
    assert result.incident.status == "pending_analysis"
    assert result.incident.failed_rule_ids == [finding.rule_id for finding in result.findings]
    assert result.incident.run_id == result.run_id
    assert next(
        stage.status for stage in result.stages if stage.name == StageName.AGENT_INTERVENTION
    ) == StageStatus.PENDING


def test_schema_drift_and_late_low_volume_are_detected(simulator: PipelineSimulator) -> None:
    schema_result = simulator.run(SCENARIOS_DIR / "schema_drift.json")
    late_result = simulator.run(SCENARIOS_DIR / "late_and_low_volume.json")

    assert "schema-v1" in {finding.rule_id for finding in schema_result.findings}
    assert {"minimum-volume", "freshness-60m"} <= {
        finding.rule_id for finding in late_result.findings
    }
    assert late_result.record_count == 2
    assert late_result.delay_minutes == 125


def test_unavailable_source_fails_pipeline_without_claiming_quality_pass(
    simulator: PipelineSimulator,
) -> None:
    result = simulator.run(SCENARIOS_DIR / "source_unavailable.json")

    assert result.pipeline_status == PipelineStatus.FAILED
    assert result.quality_status == QualityStatus.NOT_RUN
    assert result.findings == []
    assert result.errors
    assert result.record_count == 0
    assert result.output_records == []
    assert [stage.status for stage in result.stages] == [
        StageStatus.FAILED, StageStatus.SKIPPED, StageStatus.SKIPPED,
        StageStatus.PENDING, StageStatus.SKIPPED, StageStatus.SKIPPED,
    ]
    assert result.incident is not None
    assert result.incident.kind == "pipeline_failure"


def test_scenario_can_be_loaded_from_an_explicit_path(simulator: PipelineSimulator) -> None:
    scenario = Path(SCENARIOS_DIR / "healthy.json")

    result = simulator.run(scenario)

    assert result.scenario_id == "healthy-orders"


def test_local_input_is_checked_and_delivered_in_its_original_order(
    input_path: Path, simulator: PipelineSimulator,
) -> None:
    records = json.loads(input_path.read_text(encoding="utf-8"))
    records[0]["order_id"] = "LOCAL-001"
    input_path.write_text(json.dumps(records), encoding="utf-8")

    result = simulator.run(SCENARIOS_DIR / "healthy.json", input_path=input_path)

    assert result.pipeline_status == PipelineStatus.SUCCEEDED
    assert result.records == records
    assert result.output_records == records
    assert json.loads(input_path.read_text(encoding="utf-8")) == records


def test_missing_column_in_one_local_record_blocks_delivery(
    input_path: Path, simulator: PipelineSimulator,
) -> None:
    records = json.loads(input_path.read_text(encoding="utf-8"))
    del records[1]["amount"]
    input_path.write_text(json.dumps(records), encoding="utf-8")

    result = simulator.run(SCENARIOS_DIR / "healthy.json", input_path=input_path)

    assert result.pipeline_status == PipelineStatus.BLOCKED
    assert result.output_records == []
    assert {finding.rule_id for finding in result.findings} == {"schema-v1"}
    assert result.findings[0].row_indexes == [1]


def test_structured_json_values_produce_findings_without_crashing(
    input_path: Path, simulator: PipelineSimulator,
) -> None:
    records = json.loads(input_path.read_text(encoding="utf-8"))
    records[0]["order_id"] = records[1]["order_id"] = {"source_id": [1]}
    records[0]["status"] = ["unsupported"]
    records[0]["customer_id"] = {"unknown": "customer"}
    input_path.write_text(json.dumps(records), encoding="utf-8")

    result = simulator.run(SCENARIOS_DIR / "healthy.json", input_path=input_path)

    assert result.pipeline_status == PipelineStatus.BLOCKED
    assert {"unique-order", "valid-status", "known-customer"} == {
        finding.rule_id for finding in result.findings
    }


def test_quality_block_is_read_only_and_repeatable(input_path: Path) -> None:
    pipeline = load_pipeline("orders_daily")
    records = json.loads(input_path.read_text(encoding="utf-8"))
    records[0]["amount"] = -1
    original = json.dumps(records)

    first = check_quality(pipeline, records, delay_minutes=0)
    second = check_quality(pipeline, records, delay_minutes=0)

    assert first == second
    assert [finding.rule_id for finding in first] == ["valid-amount"]
    assert json.dumps(records) == original


@pytest.mark.parametrize("payload", ['{"order_id": "ORD-1"}', "[1, 2]", "{not-json"])
def test_invalid_local_input_is_rejected_without_using_demo_data(
    input_path: Path, payload: str, simulator: PipelineSimulator,
) -> None:
    input_path.write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError):
        simulator.run(SCENARIOS_DIR / "healthy.json", input_path=input_path)


def test_missing_local_file_is_not_replaced_with_demo_data(
    tmp_path: Path, simulator: PipelineSimulator,
) -> None:
    with pytest.raises(FileNotFoundError):
        simulator.run(
            SCENARIOS_DIR / "healthy.json", input_path=tmp_path / "does-not-exist.json",
        )


def test_empty_batch_cannot_advance(input_path: Path, simulator: PipelineSimulator) -> None:
    input_path.write_text("[]", encoding="utf-8")

    result = simulator.run(SCENARIOS_DIR / "healthy.json", input_path=input_path)

    assert result.pipeline_status == PipelineStatus.BLOCKED
    assert "minimum-volume" in {finding.rule_id for finding in result.findings}
    assert result.output_records == []


def test_cli_accepts_local_input(
    input_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", [
        "data-quality-sim", "--input", str(input_path),
        "--database", str(input_path.parent / "cli.sqlite3"),
    ])

    assert main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["pipeline_status"] == "succeeded"
    assert result["output_records"] == json.loads(input_path.read_text(encoding="utf-8"))


def test_cli_reports_invalid_input(
    input_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    input_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["data-quality-sim", "--input", str(input_path)])

    assert main() == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Input dataset must contain a JSON array of records" in captured.err


def test_transformation_normalizes_status_before_the_quality_gate(
    input_path: Path, simulator: PipelineSimulator,
) -> None:
    records = json.loads(input_path.read_text(encoding="utf-8"))
    records[0]["status"] = "  SETTLED  "
    input_path.write_text(json.dumps(records), encoding="utf-8")

    result = simulator.run(SCENARIOS_DIR / "healthy.json", input_path=input_path)

    assert result.pipeline_status == PipelineStatus.SUCCEEDED
    assert result.input_records[0]["status"] == "  SETTLED  "
    assert result.output_records[0]["status"] == "settled"
    assert json.loads(input_path.read_text(encoding="utf-8"))[0]["status"] == "  SETTLED  "


def test_blocked_batch_does_not_change_previous_destination_data(simulator: PipelineSimulator) -> None:
    healthy = simulator.run(SCENARIOS_DIR / "healthy.json")

    blocked = simulator.run(SCENARIOS_DIR / "quality_issues.json")

    assert blocked.pipeline_status == PipelineStatus.BLOCKED
    with closing(sqlite3.connect(healthy.destination)) as connection:
        rows = connection.execute("SELECT DISTINCT run_id FROM pipeline_output").fetchall()
    assert rows == [(healthy.run_id,)]


def test_delivery_failure_is_not_reported_as_success(tmp_path: Path) -> None:
    simulator = PipelineSimulator(database_path=tmp_path)

    result = simulator.run(SCENARIOS_DIR / "healthy.json")

    assert result.pipeline_status == PipelineStatus.FAILED
    assert result.quality_status == QualityStatus.PASS
    assert result.stages[-1].status == StageStatus.FAILED
    assert result.output_records == []
    assert result.errors
    assert result.incident is not None
    assert result.incident.kind == "pipeline_failure"


def test_delivery_mismatch_rolls_back_the_batch(simulator: PipelineSimulator) -> None:
    healthy = simulator.run(SCENARIOS_DIR / "healthy.json")
    with closing(sqlite3.connect(healthy.destination)) as connection, connection:
        connection.execute(
            "CREATE TRIGGER alter_delivery AFTER INSERT ON pipeline_output BEGIN "
            "UPDATE pipeline_output SET record_json = '{}' "
            "WHERE run_id = NEW.run_id AND position = NEW.position; END"
        )

    failed = simulator.run(SCENARIOS_DIR / "healthy.json")

    assert failed.pipeline_status == PipelineStatus.FAILED
    assert failed.output_records == []
    assert "rolled back" in failed.errors[0]
    with closing(sqlite3.connect(healthy.destination)) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM pipeline_output WHERE run_id = ?", (failed.run_id,),
        ).fetchone()[0]
    assert count == 0


def test_events_are_published_live_in_stage_order(simulator: PipelineSimulator) -> None:
    seen: list[PipelineEvent] = []
    stored_at_quality_start: list[int] = []

    def listener(event: PipelineEvent) -> None:
        seen.append(event)
        if event.kind == EventKind.STAGE_STARTED and event.stage == StageName.DATA_QUALITY:
            with closing(sqlite3.connect(simulator.destination.path)) as connection:
                tables = connection.execute(
                    "SELECT name FROM sqlite_master WHERE name = 'pipeline_output'"
                ).fetchall()
            stored_at_quality_start.append(len(tables))

    result = simulator.run(SCENARIOS_DIR / "healthy.json", on_event=listener)

    assert seen == result.events
    assert [event.sequence for event in seen] == list(range(len(seen)))
    finished = [event for event in seen if event.kind == EventKind.STAGE_FINISHED]
    assert [event.stage for event in finished] == list(StageName)
    assert [event.status for event in finished] == [stage.status for stage in result.stages]
    assert stored_at_quality_start == [0]


def test_blocked_run_logs_each_failed_rule_in_the_quality_stage(simulator: PipelineSimulator) -> None:
    result = simulator.run(SCENARIOS_DIR / "quality_issues.json")

    failures = [
        event.message.split(":")[0] for event in result.events
        if event.kind == EventKind.LOG and event.stage == StageName.DATA_QUALITY
        and event.message.startswith("FAIL ")
    ]
    assert failures == [f"FAIL {finding.rule_id}" for finding in result.findings]


def test_unexpected_input_error_closes_the_run_as_failed(
    input_path: Path, simulator: PipelineSimulator,
) -> None:
    input_path.write_text("{not-json", encoding="utf-8")
    seen: list[PipelineEvent] = []

    with pytest.raises(ValueError):
        simulator.run(SCENARIOS_DIR / "healthy.json", input_path=input_path, on_event=seen.append)

    finished = {event.stage: event.status for event in seen if event.kind == EventKind.STAGE_FINISHED}
    assert list(finished) == list(StageName)
    assert finished[StageName.INGESTION] == StageStatus.FAILED
    assert all(status == StageStatus.SKIPPED for stage, status in finished.items()
               if stage != StageName.INGESTION)
    assert any(event.level == LogLevel.ERROR for event in seen)