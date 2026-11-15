"""History of the automatic actions and the records they held back (control database)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from data_quality_agent.harness.policies import PolicyDenied
from data_quality_agent.persistence.database import Database
from data_quality_agent.persistence.models import ActionName, FailedRecord, IncidentAction


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ActionRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def claim(
        self, incident_id: str, source_run_id: str, action: ActionName, requested_by: str, *,
        request: dict[str, Any] | None = None,
    ) -> int:
        """Reserve the action; a second request for the same action on the same attempt is denied."""
        try:
            with self.database.transaction() as connection:
                cursor = connection.execute(
                    "INSERT INTO incident_actions "
                    "(incident_id, source_run_id, action, requested_by, status, requested_at, request_json) "
                    "VALUES (?, ?, ?, ?, 'running', ?, ?)",
                    (incident_id, source_run_id, action, requested_by, _now(), json.dumps(request or {})),
                )
                action_id = int(cursor.lastrowid)
                run_id = str(uuid5(NAMESPACE_URL, f"agentic-data-quality/action/{action_id}"))
                connection.execute(
                    "UPDATE incident_actions SET execution_run_id = ? WHERE action_id = ?",
                    (run_id, action_id),
                )
        except sqlite3.IntegrityError as error:
            raise PolicyDenied(f"'{action}' was already executed on attempt {source_run_id}.") from error
        return action_id

    def execution_run_id(self, action_id: int) -> str:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT execution_run_id FROM incident_actions WHERE action_id = ?", (action_id,),
            ).fetchone()
        if row is None or row["execution_run_id"] is None:
            raise ValueError(f"Action {action_id} has no idempotent execution key.")
        return row["execution_run_id"]

    def ensure_execution_run_id(self, action_id: int, preferred: str | None = None) -> str:
        candidate = preferred or str(uuid5(NAMESPACE_URL, f"agentic-data-quality/action/{action_id}"))
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT execution_run_id FROM incident_actions WHERE action_id = ?", (action_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown action '{action_id}'.")
            if row["execution_run_id"] is not None:
                return row["execution_run_id"]
            connection.execute(
                "UPDATE incident_actions SET execution_run_id = ? WHERE action_id = ?",
                (candidate, action_id),
            )
        return candidate

    def get_action(self, action_id: int) -> IncidentAction | None:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM incident_actions WHERE action_id = ?", (action_id,),
            ).fetchone()
        return self._action(row) if row else None

    def list_interrupted(self, incident_id: str) -> list[IncidentAction]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM incident_actions WHERE incident_id = ? AND status = 'running' "
                "ORDER BY action_id", (incident_id,),
            ).fetchall()
        return [self._action(row) for row in rows]

    def complete(
        self, action_id: int, *, result_run_id: str, detail: str,
        quarantined: dict[int, tuple[list[str], dict[str, Any]]] | None = None,
    ) -> None:
        with self.database.transaction() as connection:
            source_run_id = connection.execute(
                "SELECT source_run_id FROM incident_actions WHERE action_id = ?", (action_id,),
            ).fetchone()[0]
            connection.executemany(
                "INSERT OR IGNORE INTO failed_records "
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

    def list_actions(self, incident_id: str | None = None) -> list[IncidentAction]:
        query = "SELECT * FROM incident_actions"
        parameters: tuple[str, ...] = ()
        if incident_id is not None:
            query += " WHERE incident_id = ?"
            parameters = (incident_id,)
        with self.database.transaction() as connection:
            rows = connection.execute(query + " ORDER BY action_id", parameters).fetchall()
        return [self._action(row) for row in rows]

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

    @staticmethod
    def _action(row: sqlite3.Row) -> IncidentAction:
        values = dict(row)
        values["request"] = json.loads(values.pop("request_json", "{}"))
        return IncidentAction.model_validate(values)
