"""Append-only audit of local and MCP tool calls."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal

from data_quality_agent.persistence.database import Database
from data_quality_agent.persistence.models import ToolCall


class AuditRepository:
    """Append-only record of every tool call, whatever its outcome."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def record(
        self,
        *,
        agent: str,
        tool: str,
        source: Literal["local", "mcp"] | None,
        arguments: dict[str, Any],
        run_id: str | None,
        outcome: Literal["ok", "error", "blocked"],
        detail: str,
        duration_ms: int,
    ) -> int:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO tool_calls (called_at, agent, tool, source, arguments_json, run_id, outcome, "
                "detail, duration_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    datetime.now(timezone.utc).isoformat(), agent, tool, source, json.dumps(arguments, default=str),
                    run_id, outcome, detail, duration_ms,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("The tool audit record has no identifier.")
            return cursor.lastrowid

    def list_calls(
        self, *, run_id: str | None = None, run_ids: list[str] | None = None, limit: int | None = 100,
    ) -> list[ToolCall]:
        if run_ids == []:
            return []
        query = "SELECT * FROM tool_calls"
        params: list[Any] = []
        if run_id is not None:
            query, params = query + " WHERE run_id = ?", [run_id]
        elif run_ids is not None:
            query += " WHERE run_id IN (" + ", ".join("?" for _ in run_ids) + ")"
            params = run_ids
        query += " ORDER BY call_id"
        if limit is not None:
            query += " LIMIT ?"
            params = [*params, limit]
        with self.database.transaction() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            ToolCall(
                call_id=row["call_id"],
                called_at=datetime.fromisoformat(row["called_at"]),
                agent=row["agent"],
                tool=row["tool"],
                source=row["source"],
                arguments=json.loads(row["arguments_json"]),
                run_id=row["run_id"],
                outcome=row["outcome"],
                detail=row["detail"],
                duration_ms=row["duration_ms"],
            )
            for row in rows
        ]
