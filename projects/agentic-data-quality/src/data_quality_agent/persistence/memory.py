"""Short-lived, evidence-linked cross-incident memory for specialist agents."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from data_quality_agent.harness.hooks import contains_personal_data
from data_quality_agent.harness.policies import PolicyDenied
from data_quality_agent.persistence.database import Database
from data_quality_agent.persistence.models import IncidentMemory
from data_quality_agent.persistence.repository import RunRepository


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryRepository:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.runs = RunRepository(database)

    def add(
        self, *, run_id: str, content: str, source_ref: str, created_by: str, valid_days: int,
    ) -> IncidentMemory:
        summary = self.runs.get_summary(run_id)
        if summary is None:
            raise PolicyDenied("Memory can only be linked to a known pipeline run.")
        if not content.strip() or len(content) > 500:
            raise ValueError("Memory must contain 1 to 500 characters.")
        if not 1 <= valid_days <= 365:
            raise ValueError("Memory validity must be between 1 and 365 days.")
        if not created_by.strip():
            raise ValueError("A memory author is required.")
        if contains_personal_data(content):
            raise PolicyDenied("Memory cannot contain detected personal data.")
        if not source_ref.startswith("tool:"):
            raise PolicyDenied("Memory provenance must reference a successful tool result.")
        try:
            call_id = int(source_ref.removeprefix("tool:"))
        except ValueError as error:
            raise PolicyDenied("Memory provenance must reference a successful tool result.") from error
        now = _now()
        valid_until = now + timedelta(days=valid_days)
        with self.database.transaction() as connection:
            evidence = connection.execute(
                "SELECT 1 FROM tool_calls t JOIN incident_attempts a ON a.run_id = t.run_id "
                "WHERE t.call_id = ? AND t.outcome = 'ok' AND a.incident_id = "
                "(SELECT incident_id FROM incident_attempts WHERE run_id = ?) LIMIT 1",
                (call_id, run_id),
            ).fetchone()
            if evidence is None:
                raise PolicyDenied("The cited successful tool result is not evidence from this incident.")
            try:
                cursor = connection.execute(
                    "INSERT INTO incident_memories "
                    "(pipeline_id, content, source_ref, created_by, created_at, valid_until) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (summary.pipeline_id, content.strip(), source_ref, created_by.strip(),
                     now.isoformat(), valid_until.isoformat()),
                )
                memory_id = int(cursor.lastrowid)
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT memory_id FROM incident_memories "
                    "WHERE pipeline_id = ? AND source_ref = ? AND content = ?",
                    (summary.pipeline_id, source_ref, content.strip()),
                ).fetchone()
                memory_id = int(row["memory_id"])
        return self.get(memory_id)

    def get(self, memory_id: int) -> IncidentMemory:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM incident_memories WHERE memory_id = ?", (memory_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"Unknown memory '{memory_id}'.")
        return IncidentMemory.model_validate(dict(row))

    def active_for_pipeline(self, pipeline_id: str, *, limit: int = 5) -> list[IncidentMemory]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM incident_memories WHERE pipeline_id = ? AND valid_until > ? "
                "ORDER BY created_at DESC LIMIT ?",
                (pipeline_id, _now().isoformat(), limit),
            ).fetchall()
        return [IncidentMemory.model_validate(dict(row)) for row in rows]

    @staticmethod
    def as_evidence(memories: list[IncidentMemory]) -> list[dict[str, Any]]:
        return [
            {
                "ref": f"memory:{memory.memory_id}",
                "content": memory.content,
                "source_ref": memory.source_ref,
                "created_at": memory.created_at.isoformat(),
                "valid_until": memory.valid_until.isoformat(),
            }
            for memory in memories
        ]
