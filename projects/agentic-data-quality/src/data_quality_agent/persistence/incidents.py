"""Stable incident identity, linked correction attempts and agent reports."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from data_quality_agent.agents.models import OrchestrationResult
from data_quality_agent.persistence.database import Database
from data_quality_agent.persistence.models import AgentSession, AgentStep, IncidentState, IncidentWorkflow, RunSummary
from data_quality_agent.persistence.repository import RunRepository


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class IncidentRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def register(self, run_id: str) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO incident_workflows VALUES (?, ?, 'awaiting_correction', ?)",
                (run_id, run_id, _now()),
            )
            connection.execute("INSERT INTO incident_attempts VALUES (?, ?, NULL)", (run_id, run_id))

    def get_for_run(self, run_id: str) -> IncidentWorkflow | None:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT w.* FROM incident_workflows w JOIN incident_attempts a USING (incident_id) "
                "WHERE a.run_id = ?", (run_id,),
            ).fetchone()
        return IncidentWorkflow.model_validate(dict(row)) if row else None

    def list_attempts(self, incident_id: str) -> list[RunSummary]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT run_id FROM incident_attempts WHERE incident_id = ? ORDER BY rowid",
                (incident_id,),
            ).fetchall()
        runs = RunRepository(self.database)
        summaries = []
        for row in rows:
            summary = runs.get_summary(row["run_id"])
            if summary is None:
                raise RuntimeError("An incident attempt has no pipeline run.")
            summaries.append(summary)
        return summaries

    def claim_correction(self, incident: IncidentWorkflow) -> None:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE incident_workflows SET status = 'correcting', updated_at = ? "
                "WHERE incident_id = ? AND latest_run_id = ? "
                "AND status IN ('awaiting_correction', 'unresolved', 'analysis_failed') "
                "AND NOT EXISTS (SELECT 1 FROM agent_sessions WHERE run_id = latest_run_id AND status = 'running')",
                (_now(), incident.incident_id, incident.latest_run_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("O incidente mudou, está em processamento ou já foi resolvido. Atualiza a página.")

    def add_attempt(self, incident_id: str, run_id: str, reason: str) -> None:
        with self.database.transaction() as connection:
            connection.execute("INSERT INTO incident_attempts VALUES (?, ?, ?)", (run_id, incident_id, reason))
            connection.execute(
                "UPDATE incident_workflows SET latest_run_id = ?, updated_at = ? WHERE incident_id = ?",
                (run_id, _now(), incident_id),
            )

    def set_status(self, incident_id: str, status: IncidentState, *, run_id: str) -> None:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE incident_workflows SET status = ?, updated_at = ? "
                "WHERE incident_id = ? AND latest_run_id = ?",
                (status, _now(), incident_id, run_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("A tentativa já não é a mais recente deste incidente.")

    def release_correction(self, incident_id: str) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE incident_workflows SET status = 'awaiting_correction', updated_at = ? "
                "WHERE incident_id = ? AND status = 'correcting'", (_now(), incident_id),
            )

    def start_session(self, session_id: str, run_id: str) -> None:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE incident_workflows SET status = 'investigating', updated_at = ? "
                "WHERE latest_run_id = ? AND status NOT IN ('investigating', 'correcting')",
                (_now(), run_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Este incidente já está em processamento ou a tentativa mudou.")
            connection.execute(
                "INSERT INTO agent_sessions (session_id, run_id, status, started_at) VALUES (?, ?, 'running', ?)",
                (session_id, run_id, _now()),
            )

    def append_step(self, session_id: str, agent: str, kind: str, message: str) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO agent_steps (session_id, timestamp, agent, kind, message) VALUES (?, ?, ?, ?, ?)",
                (session_id, _now(), agent, kind, message),
            )

    def finish_session(
        self, session_id: str, *, outcome: OrchestrationResult | None = None, error: str | None = None,
    ) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE agent_sessions SET status = ?, finished_at = ?, outcome_json = ?, error = ? "
                "WHERE session_id = ?",
                ("failed" if error else "completed", _now(),
                 outcome.model_dump_json() if outcome else None, error, session_id),
            )

    def list_sessions(self, run_id: str) -> list[AgentSession]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_sessions WHERE run_id = ? ORDER BY rowid", (run_id,),
            ).fetchall()
        return [
            AgentSession(
                **{key: row[key] for key in row.keys() if key != "outcome_json"},
                outcome=json.loads(row["outcome_json"]) if row["outcome_json"] else None,
            )
            for row in rows
        ]

    def list_steps(self, session_id: str) -> list[AgentStep]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT timestamp, agent, kind, message FROM agent_steps WHERE session_id = ? ORDER BY step_id",
                (session_id,),
            ).fetchall()
        return [AgentStep.model_validate(dict(row)) for row in rows]
