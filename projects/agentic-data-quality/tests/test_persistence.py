import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from data_quality_agent.persistence import Database
from data_quality_agent.evaluation import evaluate_cases
from data_quality_agent.evaluation.storage import EvaluationRepository
from data_quality_agent.mcp.platform import PLATFORM_DATABASE
from data_quality_agent.persistence.audit import AuditRepository
from data_quality_agent.persistence.database import MIGRATIONS
from data_quality_agent.persistence.incidents import IncidentRepository
from data_quality_agent.persistence.memory import MemoryRepository
from data_quality_agent.persistence.models import ModelCall
from data_quality_agent.persistence.repository import definition_version
from data_quality_agent.persistence.telemetry import TelemetryRepository
from data_quality_agent.service import PipelineService
from data_quality_agent.simulator.destination import SQLiteDestination
from data_quality_agent.simulator.engine import DATASETS_DIR, SCENARIOS_DIR, load_pipeline
from data_quality_agent.simulator.models import StageName, StageStatus


@pytest.fixture
def service(tmp_path: Path) -> PipelineService:
    return PipelineService(tmp_path / "history.sqlite3")


def test_every_run_is_stored_and_rebuilt_exactly(service: PipelineService) -> None:
    results = [
        service.run(SCENARIOS_DIR / name)
        for name in ("healthy.json", "quality_issues.json", "source_unavailable.json")
    ]

    for result in results:
        assert service.runs.get_run(result.run_id) == result
    assert [run.status for run in service.runs.list_runs()] == ["failed", "blocked", "succeeded"]
    blocked = results[1]
    assert service.runs.get_incident(blocked.run_id).failed_rule_ids == blocked.incident.failed_rule_ids
    assert service.runs.get_records(blocked.run_id, "transformed") == blocked.records
    assert service.runs.get_output(blocked.run_id) == []
    assert service.runs.get_output(results[0].run_id) == results[0].records


def test_approved_data_goes_only_to_the_separate_warehouse(service: PipelineService) -> None:
    healthy = service.run(SCENARIOS_DIR / "healthy.json")
    service.run(SCENARIOS_DIR / "quality_issues.json")

    warehouse = service.database.path.parent / "warehouse.sqlite3"
    assert Path(healthy.destination) == warehouse.resolve()
    with closing(sqlite3.connect(service.database.path)) as connection:
        control_tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    with closing(sqlite3.connect(warehouse)) as connection:
        delivered = connection.execute("SELECT DISTINCT run_id FROM pipeline_output").fetchall()
    assert "pipeline_output" not in control_tables
    assert {"pipeline_runs", "run_events", "quality_findings", "incidents"} <= control_tables
    assert delivered == [(healthy.run_id,)]


def test_a_run_interrupted_by_an_error_is_closed_as_failed(service: PipelineService, tmp_path: Path) -> None:
    bad_input = tmp_path / "bad.json"
    bad_input.write_text(json.dumps({"not": "a list"}), encoding="utf-8")

    with pytest.raises(ValueError):
        service.run(SCENARIOS_DIR / "healthy.json", input_path=bad_input)

    [summary] = service.runs.list_runs()
    assert summary.status == "failed"
    assert "JSON array" in summary.errors[0]
    stages = {stage.name: stage.status for stage in service.runs.get_stages(summary.run_id)}
    assert stages[StageName.INGESTION] == StageStatus.FAILED
    assert stages[StageName.DELIVERY] == StageStatus.SKIPPED


def test_an_existing_destination_file_keeps_its_data_as_the_warehouse(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "CREATE TABLE pipeline_output (run_id TEXT NOT NULL, pipeline_id TEXT NOT NULL, "
            "scenario_id TEXT NOT NULL, position INTEGER NOT NULL, record_json TEXT NOT NULL, "
            "PRIMARY KEY (run_id, position))"
        )
        connection.execute("INSERT INTO pipeline_output VALUES ('old', 'orders_daily', 's', 0, '{}')")

    result = PipelineService(tmp_path / "control.sqlite3", warehouse_path=path).run(SCENARIOS_DIR / "healthy.json")

    assert SQLiteDestination(path).read("old") == [{}]
    assert SQLiteDestination(path).read(result.run_id) == result.records


def test_migrations_bring_an_older_control_database_up_to_date(tmp_path: Path) -> None:
    path = tmp_path / "control.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        for script in MIGRATIONS[:2]:
            connection.executescript(script)
        connection.executemany("INSERT INTO schema_migrations VALUES (?, 'x')", [(1,), (2,)])

    Database(path)
    database = Database(path)

    assert database.schema_version == len(MIGRATIONS)
    with database.transaction() as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name = 'pipeline_output'").fetchall() == []


def test_existing_incidents_get_a_stable_workflow_when_migrated(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite3"
    pipeline = load_pipeline("orders_daily")
    version = definition_version(pipeline)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        for script in MIGRATIONS[:3]:
            connection.executescript(script)
        connection.executemany("INSERT INTO schema_migrations VALUES (?, 'x')", [(1,), (2,), (3,)])
        connection.execute(
            "INSERT INTO pipelines VALUES (?, ?, ?, ?, '2026-11-15T00:00:00+00:00')",
            (pipeline.pipeline_id, version, pipeline.name, pipeline.model_dump_json()),
        )
        connection.execute(
            "INSERT INTO pipeline_runs (run_id, pipeline_id, pipeline_version, scenario_id, seed, "
            "status, destination, started_at) VALUES ('old-run', ?, ?, 'old-scenario', 0, 'blocked', ?, ?)",
            (pipeline.pipeline_id, version, str(tmp_path / "warehouse.sqlite3"), "2026-11-15T00:00:00+00:00"),
        )
        connection.execute(
            "INSERT INTO incidents VALUES ('old-run', ?, 'data_quality', 'pending_analysis', "
            "'Invalid batch', '[]', '2026-11-15T00:00:00+00:00')", (pipeline.pipeline_id,),
        )
    incident = IncidentRepository(Database(path)).get_for_run("old-run")
    assert incident.incident_id == incident.latest_run_id == "old-run"
    assert incident.status == "awaiting_correction"


def test_clean_clears_all_workspace_data_but_preserves_sources_and_schema(service: PipelineService) -> None:
    original = service.run(SCENARIOS_DIR / "few_invalid_records.json")
    service.incidents.start_session("clean-test", original.run_id)
    action = service.quarantine_failed_records(original.run_id, requested_by="remediation")
    service.incidents.finish_session("clean-test", error="Stopped for review.")
    record = service.actions.list_failed_records(original.run_id)[0]
    service.approvals.request(
        source_run_id=record.source_run_id, position=record.position, target_status="discarded",
        reason="Review row", requested_by="analyst", identity_attested=True,
    )
    pipeline = service.current_pipeline("orders_daily")
    rule_approval = service.rule_changes.request(
        incident_id=original.run_id, pipeline=pipeline, rule_id="minimum-volume",
        attribute="minimum_count", proposed_value=25, reason="Partial delivery",
        requested_by="analyst", identity_attested=True,
    )
    service.rule_changes.approve(
        rule_approval, pipeline=pipeline, decided_by="reviewer", identity_attested=True,
    )
    call_id = AuditRepository(service.database).record(
        agent="diagnosis", tool="get_run", source="local", arguments={}, run_id=original.run_id,
        outcome="ok", detail="Evidence", duration_ms=1,
    )
    MemoryRepository(service.database).add(
        run_id=original.run_id, content="Review invalid amounts.", source_ref=f"tool:{call_id}",
        created_by="diagnosis", valid_days=1,
    )
    TelemetryRepository(service.database).record(ModelCall(
        session_id="clean-test", run_id=original.run_id, agent="diagnosis", model_name="test-model",
        provider="test", started_at=original.events[0].timestamp, duration_ms=1, outcome="ok",
        input_tokens=10, output_tokens=5,
    ))
    evaluation_root = service.database.path.parent / "evaluations"
    saved = evaluate_cases(scenario_ids=["healthy-orders"], workdir=evaluation_root)
    EvaluationRepository(service.database).save(saved)
    orphan = evaluate_cases(scenario_ids=["healthy-orders"], workdir=evaluation_root)
    controls = [service.database.path]
    for report in (saved, orphan):
        assert report.results[0].control_database is not None
        controls.append(Path(report.results[0].control_database))
    warehouses = [SQLiteDestination(path.parent / "warehouse.sqlite3") for path in controls]
    assert warehouses[0].read(action["new_run_id"])
    untouched = [
        PLATFORM_DATABASE, DATASETS_DIR / "orders.json", SCENARIOS_DIR / "healthy.json",
        service.database.path.parent / "unrelated.sqlite3", evaluation_root / "notes.txt",
    ]
    untouched[-2].write_bytes(b"Unrelated database placeholder")
    untouched[-1].write_text("Keep this note.", encoding="utf-8")
    snapshots = {path: path.read_bytes() for path in untouched}

    service.clean()
    service.clean()

    for path in controls:
        database = Database(path)
        assert database.schema_version == len(MIGRATIONS)
        with database.transaction() as connection:
            tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name != 'schema_migrations'"
            ).fetchall()
            for table in tables:
                assert connection.execute(f'SELECT COUNT(*) FROM "{table["name"]}"').fetchone()[0] == 0
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    for warehouse in warehouses:
        with closing(sqlite3.connect(warehouse.path)) as connection:
            assert connection.execute("SELECT COUNT(*) FROM pipeline_output").fetchone()[0] == 0
    assert {path: path.read_bytes() for path in untouched} == snapshots
    assert service.current_pipeline("orders_daily") == pipeline
    restarted = PipelineService(service.database.path).run(SCENARIOS_DIR / "healthy.json")
    assert restarted.pipeline_status == "succeeded"
    assert [run.run_id for run in service.runs.list_runs()] == [restarted.run_id]


def test_cleaning_an_unused_workspace_does_not_create_a_warehouse(service: PipelineService) -> None:
    service.clean()

    assert service.runs.list_runs() == []
    assert not service.simulator.destination.path.exists()
    assert not (service.database.path.parent / "evaluations").exists()
