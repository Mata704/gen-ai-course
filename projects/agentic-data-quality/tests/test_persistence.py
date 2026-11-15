import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from data_quality_agent.persistence import Database
from data_quality_agent.persistence.database import MIGRATIONS
from data_quality_agent.persistence.incidents import IncidentRepository
from data_quality_agent.persistence.repository import definition_version
from data_quality_agent.service import PipelineService
from data_quality_agent.simulator.destination import SQLiteDestination
from data_quality_agent.simulator.engine import SCENARIOS_DIR, load_pipeline
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
