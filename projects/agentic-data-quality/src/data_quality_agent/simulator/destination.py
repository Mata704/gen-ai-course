"""The destination (a small warehouse): its own SQLite file that only ever receives approved batches.

It is separate from the control database (run history, logs, findings, incidents, audit), as a real
warehouse is separate from the system that orchestrates the pipeline.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

__all__ = ["DEFAULT_WAREHOUSE", "DeliveryVerificationError", "SQLiteDestination"]

DEFAULT_WAREHOUSE = Path("runs") / "warehouse.sqlite3"

# Same columns as the table older versions created, so an existing destination file keeps working.
SCHEMA = """
CREATE TABLE IF NOT EXISTS pipeline_output (
    run_id TEXT NOT NULL,
    pipeline_id TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    record_json TEXT NOT NULL,
    PRIMARY KEY (run_id, position)
)
"""


class DeliveryVerificationError(RuntimeError):
    """The destination did not return the approved records unchanged."""


class SQLiteDestination:
    """Final load of an approved batch into `pipeline_output`, in one verified transaction."""

    def __init__(self, path: str | Path = DEFAULT_WAREHOUSE) -> None:
        self.path = Path(path)

    def load(
        self,
        *,
        run_id: str,
        pipeline_id: str,
        scenario_id: str,
        records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as connection, connection:
            connection.execute(SCHEMA)
            connection.executemany(
                "INSERT OR REPLACE INTO pipeline_output "
                "(run_id, pipeline_id, scenario_id, position, record_json) VALUES (?, ?, ?, ?, ?)",
                [
                    (run_id, pipeline_id, scenario_id, index, json.dumps(record, allow_nan=False))
                    for index, record in enumerate(records)
                ],
            )
            output_records = self._select(connection, run_id)
            if output_records != records:
                raise DeliveryVerificationError("SQLite delivery could not be verified; batch rolled back.")
        return output_records

    def delete_run(self, run_id: str) -> None:
        """Remove an incomplete run's prior delivery before replaying that same idempotency key."""
        if not self.path.is_file():
            return
        with closing(sqlite3.connect(self.path, timeout=10)) as connection, connection:
            connection.execute("DELETE FROM pipeline_output WHERE run_id = ?", (run_id,))

    def read(self, run_id: str) -> list[dict[str, Any]]:
        """Records delivered by a run; empty if nothing was ever loaded here. Never creates the file."""
        if not self.path.is_file():
            return []
        uri = self.path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=10)) as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'pipeline_output'"
            ).fetchone()
            return self._select(connection, run_id) if exists else []

    @staticmethod
    def _select(connection: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT record_json FROM pipeline_output WHERE run_id = ? ORDER BY position", (run_id,),
        ).fetchall()
        return [json.loads(row[0]) for row in rows]
