from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

DEFAULT_DATABASE = Path("runs") / "pipelines.sqlite3"


class DeliveryVerificationError(RuntimeError):
    """The destination did not return the approved records unchanged."""


class SQLiteDestination:
    def __init__(self, path: str | Path = DEFAULT_DATABASE) -> None:
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
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS pipeline_output ("
                "run_id TEXT NOT NULL, pipeline_id TEXT NOT NULL, scenario_id TEXT NOT NULL, "
                "position INTEGER NOT NULL, record_json TEXT NOT NULL, "
                "PRIMARY KEY (run_id, position))"
            )
            connection.executemany(
                "INSERT INTO pipeline_output "
                "(run_id, pipeline_id, scenario_id, position, record_json) VALUES (?, ?, ?, ?, ?)",
                [
                    (run_id, pipeline_id, scenario_id, index, json.dumps(record, allow_nan=False))
                    for index, record in enumerate(records)
                ],
            )
            stored = connection.execute(
                "SELECT record_json FROM pipeline_output WHERE run_id = ? ORDER BY position",
                (run_id,),
            ).fetchall()
            output_records = [json.loads(row[0]) for row in stored]
            if output_records != records:
                raise DeliveryVerificationError("SQLite delivery could not be verified; batch rolled back.")
        return output_records
