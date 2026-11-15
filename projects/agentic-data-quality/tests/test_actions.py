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
    assert migrated.schema_version == 7
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


def test_failed_record_disposition_requires_distinct_human_approval(tmp_path: Path) -> None:
    service = PipelineService(tmp_path / "history.sqlite3")
    run_id = investigating(service, "few_invalid_records.json")
    service.quarantine_failed_records(run_id, requested_by="test")
    [record] = service.actions.list_failed_records(run_id)[:1]
    approval_id = service.approvals.request(
        source_run_id=record.source_run_id, position=record.position, target_status="discarded",
        reason="Reviewed and deemed unusable.", requested_by="analyst",
    )
    with pytest.raises(PolicyDenied, match="different person"):
        service.approvals.approve(approval_id, decided_by="analyst")
    approved = service.approvals.approve(approval_id, decided_by="reviewer")
    assert (approved.status, approved.decided_by) == ("executed", "reviewer")
    updated = service.actions.list_failed_records(run_id)[0]
    assert updated.status == "discarded"

    second = service.actions.list_failed_records(run_id)[1]
    stale_approval = service.approvals.request(
        source_run_id=second.source_run_id, position=second.position, target_status="released",
        reason="Review the row.", requested_by="analyst",
    )
    with service.database.transaction() as connection:
        connection.execute(
            "UPDATE failed_records SET status = 'discarded' "
            "WHERE source_run_id = ? AND position = ?",
            (second.source_run_id, second.position),
        )
    with pytest.raises(PolicyDenied, match="Only a held"):
        service.approvals.approve(stale_approval, decided_by="reviewer")


def test_interrupted_action_recovery_reuses_the_same_run_and_delivery(tmp_path: Path) -> None:
    service = PipelineService(tmp_path / "history.sqlite3")
    source = service.run(SCENARIOS_DIR / "source_unavailable.json")
    source_id = source.run_id
    service.incidents.start_session("interrupted", source_id)
    action_id = service.actions.claim(
        source_id, source_id, "retry_ingestion", "remediation",
        request={"source_status": "operational"},
    )
    with pytest.raises(PolicyDenied, match="still active"):
        service.recover_interrupted_actions(source_id)
    execution_id = service.actions.execution_run_id(action_id)
    pipeline = service._stored_pipeline(source_id)
    scenario = service._bundled_scenario(source.scenario_id).model_copy(update={"faults": []})
    result = service._run(
        scenario, pipeline, incident_id=source_id, reason="Interrupted action simulation.",
        destination_path=source.destination, run_id=execution_id,
    )
    with service.database.transaction() as connection:
        connection.execute(
            "UPDATE agent_sessions SET started_at = '2000-01-01T00:00:00+00:00' "
            "WHERE session_id = 'interrupted'",
        )
        connection.execute(
            "UPDATE pipeline_runs SET status = 'running', finished_at = NULL WHERE run_id = ?",
            (execution_id,),
        )
    assert len(service.runs.get_output(execution_id)) == 40

    [recovered] = service.recover_interrupted_actions(source_id)

    assert recovered["run_id"] == result.run_id == execution_id
    assert len(service.runs.get_output(execution_id)) == 40
    [action] = service.actions.list_actions(source_id)
    assert (action.status, action.result_run_id) == ("executed", execution_id)
