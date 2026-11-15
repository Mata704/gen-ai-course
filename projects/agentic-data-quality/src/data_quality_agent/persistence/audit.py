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
    ) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO tool_calls (called_at, agent, tool, source, arguments_json, run_id, outcome, "
                "detail, duration_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    datetime.now(timezone.utc).isoformat(), agent, tool, source, json.dumps(arguments, default=str),
                    run_id, outcome, detail, duration_ms,
                ),
            )

    def list_calls(self, *, run_id: str | None = None, limit: int = 100) -> list[ToolCall]:
        query, params = "SELECT * FROM tool_calls", ()
        if run_id is not None:
            query, params = query + " WHERE run_id = ?", (run_id,)
        with self.database.transaction() as connection:
            rows = connection.execute(query + " ORDER BY call_id LIMIT ?", (*params, limit)).fetchall()
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
