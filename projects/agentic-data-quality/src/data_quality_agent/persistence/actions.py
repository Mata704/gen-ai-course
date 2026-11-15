"""History of the automatic actions and the records they held back (control database)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from data_quality_agent.harness.policies import PolicyDenied
from data_quality_agent.persistence.database import Database
from data_quality_agent.persistence.models import ActionName, FailedRecord, IncidentAction


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ActionRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def claim(self, incident_id: str, source_run_id: str, action: ActionName, requested_by: str) -> int:
        """Reserve the action; a second request for the same action on the same attempt is denied."""
        try:
            with self.database.transaction() as connection:
                cursor = connection.execute(
                    "INSERT INTO incident_actions "
                    "(incident_id, source_run_id, action, requested_by, status, requested_at) "
                    "VALUES (?, ?, ?, ?, 'running', ?)",
                    (incident_id, source_run_id, action, requested_by, _now()),
                )
        except sqlite3.IntegrityError as error:
            raise PolicyDenied(f"'{action}' was already executed on attempt {source_run_id}.") from error
        return int(cursor.lastrowid)

    def complete(
        self, action_id: int, *, result_run_id: str, detail: str,
        quarantined: dict[int, tuple[list[str], dict[str, Any]]] | None = None,
    ) -> None:
        with self.database.transaction() as connection:
            source_run_id = connection.execute(
                "SELECT source_run_id FROM incident_actions WHERE action_id = ?", (action_id,),
            ).fetchone()[0]
            connection.executemany(
                "INSERT INTO failed_records "
                "(source_run_id, position, action_id, rule_ids_json, record_json) VALUES (?, ?, ?, ?, ?)",
                [
                    (source_run_id, position, action_id, json.dumps(rules), json.dumps(record, default=str))
                    for position, (rules, record) in sorted((quarantined or {}).items())
                ],
            )
            connection.execute(
                "UPDATE incident_actions SET status = 'executed', result_run_id = ?, detail = ?, finished_at = ? "
                "WHERE action_id = ?",
                (result_run_id, detail, _now(), action_id),
            )

    def fail(self, action_id: int, detail: str) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE incident_actions SET status = 'failed', detail = ?, finished_at = ? WHERE action_id = ?",
                (detail, _now(), action_id),
            )

    def count_executed(self, incident_id: str, action: ActionName) -> int:
        with self.database.transaction() as connection:
            return connection.execute(
                "SELECT COUNT(*) FROM incident_actions WHERE incident_id = ? AND action = ? AND status = 'executed'",
                (incident_id, action),
            ).fetchone()[0]

    def list_actions(self, incident_id: str) -> list[IncidentAction]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM incident_actions WHERE incident_id = ? ORDER BY action_id", (incident_id,),
            ).fetchall()
        return [IncidentAction.model_validate(dict(row)) for row in rows]

    def list_failed_records(self, incident_id: str) -> list[FailedRecord]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT q.* FROM failed_records q JOIN incident_actions a USING (action_id) "
                "WHERE a.incident_id = ? ORDER BY q.action_id, q.position", (incident_id,),
            ).fetchall()
        return [
            FailedRecord(
                source_run_id=row["source_run_id"], position=row["position"], action_id=row["action_id"],
                rule_ids=json.loads(row["rule_ids_json"]), record=json.loads(row["record_json"]),
                status=row["status"],
            )
            for row in rows
        ]
