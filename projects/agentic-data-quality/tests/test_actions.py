import sqlite3
from pathlib import Path

import pytest

from data_quality_agent.harness.policies import PolicyDenied, check_retry
from data_quality_agent.persistence.database import Database
from data_quality_agent.service import PipelineService
from data_quality_agent.simulator.engine import SCENARIOS_DIR


def test_migration_moves_legacy_quarantine_rows_to_failed_records(tmp_path: Path) -> None:
    path = tmp_path / "history.sqlite3"
    database = Database(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO failed_records "
            "(source_run_id, position, action_id, rule_ids_json, record_json) VALUES (?, ?, ?, ?, ?)",
            ("old-run", 3, 1, '["valid-amount"]', '{"id":"failed"}'),
        )
        connection.execute("ALTER TABLE failed_records RENAME TO quarantined_records")
        connection.execute("ALTER TABLE quarantined_records DROP COLUMN status")
        connection.execute("DELETE FROM schema_migrations WHERE version = 6")

    migrated = Database(path)
    with migrated.transaction() as connection:
        row = connection.execute("SELECT * FROM failed_records").fetchone()
        old_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'quarantined_records'"
        ).fetchone()
    assert migrated.schema_version == 6
    assert row["source_run_id"] == "old-run"
    assert row["record_json"] == '{"id":"failed"}'
    assert row["status"] == "held"
    assert old_table is None


def investigating(service: PipelineService, scenario: str) -> str:
    run = service.run(SCENARIOS_DIR / scenario)
    service.incidents.start_session("session", run.run_id)
    return run.run_id


def test_retry_runs_only_when_the_source_is_available_and_once_per_attempt(tmp_path: Path) -> None:
    service = PipelineService(tmp_path / "history.sqlite3")
    run = service.run(SCENARIOS_DIR / "source_unavailable.json")
    with pytest.raises(PolicyDenied, match="investigation"):
        service.retry_ingestion(run.run_id, requested_by="test", source_status="operational")

    service.incidents.start_session("session", run.run_id)
    with pytest.raises(PolicyDenied, match="'down'"):
        service.retry_ingestion(run.run_id, requested_by="test", source_status="down")
    result = service.retry_ingestion(run.run_id, requested_by="test", source_status="operational")
    assert (result["status"], result["pipeline_status"], result["records_delivered"]) == ("executed", "succeeded", 40)
    assert "records" not in result
    with pytest.raises(PolicyDenied, match="latest attempt"):
        service.retry_ingestion(run.run_id, requested_by="test", source_status="operational")


def test_retry_budget_and_kind_come_from_the_pipeline_policy(tmp_path: Path) -> None:
    service = PipelineService(tmp_path / "history.sqlite3")
    run_id = investigating(service, "source_unavailable.json")
    run = service.runs.get_run(run_id)
    pipeline = service._stored_pipeline(run_id)
    with pytest.raises(PolicyDenied, match="2 automatic retries"):
        check_retry(incident_kind="pipeline_failure", run=run, pipeline=pipeline, retries_done=2,
                    source_status="operational")
    with pytest.raises(PolicyDenied, match="failed pipeline run"):
        check_retry(incident_kind="data_quality", run=run, pipeline=pipeline, retries_done=0,
                    source_status="operational")


def test_quarantine_cannot_fix_batch_level_rules(tmp_path: Path) -> None:
    service = PipelineService(tmp_path / "history.sqlite3")
    run_id = investigating(service, "late_and_low_volume.json")
    with pytest.raises(PolicyDenied, match="whole batch"):
        service.quarantine_failed_records(run_id, requested_by="test")
    assert service.actions.list_actions(run_id) == []


def test_the_same_action_runs_once_on_an_attempt(tmp_path: Path) -> None:
    service = PipelineService(tmp_path / "history.sqlite3")
    run_id = investigating(service, "few_invalid_records.json")
    service.actions.claim(run_id, run_id, "quarantine_failed_records", "test")
    with pytest.raises(PolicyDenied, match="already executed"):
        service.quarantine_failed_records(run_id, requested_by="test")
