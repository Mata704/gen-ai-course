"""Orders Platform: the external, read-only data source served by the MCP server.

It stands for a system owned by the team that produces the orders data. It already exists with its
data before any pipeline runs, and nothing in this project writes to it: the server opens the
shipped SQLite file in read-only mode. Our own data (runs, incidents, audit) lives in a separate
local database.

    uv run --locked python -m data_quality_agent.mcp.platform   # rebuild the file from platform.sql
"""

# No `from __future__ import annotations`: the MCP server reads these annotations at runtime.
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from fastmcp.exceptions import ToolError
from pydantic import Field

DATA_DIR = Path(__file__).parent / "data"
PLATFORM_DATABASE = DATA_DIR / "orders_platform.sqlite3"
PLATFORM_SEED = DATA_DIR / "platform.sql"


class PlatformError(ToolError):
    """The request does not match anything in the platform (sent to the client as a tool error)."""


def build_platform_database(target: Path, seed: Path = PLATFORM_SEED) -> Path:
    """Create the platform file from its SQL snapshot (maintenance only; the server never writes)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(target.name + ".tmp")
    staging.unlink(missing_ok=True)
    with closing(sqlite3.connect(staging)) as connection, connection:
        connection.executescript(seed.read_text(encoding="utf-8"))
    staging.replace(target)
    return target


class PlatformTools:
    """Read-only queries over the platform; every method is one MCP tool."""

    def __init__(self, database: str | Path = PLATFORM_DATABASE) -> None:
        self.path = Path(database)
        if not self.path.is_file():
            raise FileNotFoundError(f"Platform database not found: {self.path}")

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        # mode=ro: SQLite itself rejects any write, whatever the server code does.
        uri = f"{self.path.resolve().as_uri()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            yield connection

    def get_dataset_contract(self, dataset_id: str) -> dict[str, Any]:
        """Data contract published by the producing team for a dataset: owner, delivery schedule,
        freshness SLA, minimum daily rows and the expected columns with their allowed values."""
        with self._read() as connection:
            dataset = connection.execute(
                "SELECT d.*, s.owner_team, s.owner_contact FROM datasets d "
                "JOIN source_systems s USING (system_id) WHERE dataset_id = ?", (dataset_id,),
            ).fetchone()
            if dataset is None:
                raise PlatformError(f"Unknown dataset '{dataset_id}'.")
            columns = connection.execute(
                "SELECT * FROM dataset_columns WHERE dataset_id = ? ORDER BY position", (dataset_id,),
            ).fetchall()
        return {
            "dataset_id": dataset_id,
            "source_system": dataset["system_id"],
            "description": dataset["description"],
            "contract_version": dataset["contract_version"],
            "owner_team": dataset["owner_team"],
            "owner_contact": dataset["owner_contact"],
            "delivery_schedule": dataset["delivery_schedule"],
            "freshness_sla_minutes": dataset["freshness_sla_minutes"],
            "expected_daily_rows_min": dataset["expected_daily_rows_min"],
            "columns": [
                {
                    "name": column["column_name"],
                    "type": column["data_type"],
                    "nullable": bool(column["nullable"]),
                    "allowed_values": column["allowed_values"].split(",") if column["allowed_values"] else None,
                    "description": column["description"],
                }
                for column in columns
            ],
        }

    def list_schema_changes(
        self,
        dataset_id: str,
        status: Literal["scheduled", "released", "rolled_back"] | None = None,
    ) -> dict[str, Any]:
        """Schema changes announced by the producing team for a dataset (added, renamed or removed
        columns and new allowed values), with their effective date and status."""
        query = "SELECT * FROM schema_changes WHERE dataset_id = ?"
        params: tuple[Any, ...] = (dataset_id,)
        if status is not None:
            query, params = query + " AND status = ?", (*params, status)
        with self._read() as connection:
            self._require(connection, "datasets", "dataset_id", dataset_id)
            rows = connection.execute(query + " ORDER BY announced_at DESC", params).fetchall()
        return {
            "dataset_id": dataset_id,
            "changes": [
                {
                    "change_id": row["change_id"],
                    "change_type": row["change_type"],
                    "column": row["column_name"],
                    "status": row["status"],
                    "announced_at": row["announced_at"],
                    "effective_from": row["effective_from"],
                    "description": row["description"],
                }
                for row in rows
            ],
        }

    def get_source_status(self, system_id: str) -> dict[str, Any]:
        """Current status of a source system as reported by its owners, with its planned
        maintenance windows. The status is a snapshot: check `status_as_of`."""
        with self._read() as connection:
            system = connection.execute(
                "SELECT * FROM source_systems WHERE system_id = ?", (system_id,),
            ).fetchone()
            if system is None:
                raise PlatformError(f"Unknown source system '{system_id}'.")
            windows = connection.execute(
                "SELECT * FROM maintenance_windows WHERE system_id = ? ORDER BY rowid", (system_id,),
            ).fetchall()
        return {
            "system_id": system_id,
            "name": system["name"],
            "owner_team": system["owner_team"],
            "status": system["status"],
            "status_message": system["status_message"],
            "status_as_of": system["status_as_of"],
            "maintenance_windows": [
                {"recurrence": w["recurrence"], "start_utc": w["start_utc"], "end_utc": w["end_utc"],
                 "description": w["description"]}
                for w in windows
            ],
        }

    def list_upstream_incidents(
        self,
        system_id: str,
        status: Literal["open", "resolved"] | None = None,
        limit: Annotated[int, Field(ge=1, le=10)] = 5,
    ) -> dict[str, Any]:
        """Incidents opened by the producing team on a source system, newest first. Descriptions
        are free text written by people."""
        query = "SELECT * FROM upstream_incidents WHERE system_id = ?"
        params: tuple[Any, ...] = (system_id,)
        if status is not None:
            query, params = query + " AND status = ?", (*params, status)
        with self._read() as connection:
            self._require(connection, "source_systems", "system_id", system_id)
            rows = connection.execute(query + " ORDER BY opened_at DESC LIMIT ?", (*params, limit)).fetchall()
        return {
            "system_id": system_id,
            "incidents": [
                {
                    "incident_id": row["incident_id"],
                    "severity": row["severity"],
                    "status": row["status"],
                    "opened_at": row["opened_at"],
                    "resolved_at": row["resolved_at"],
                    "title": row["title"],
                    "description": row["description"],
                }
                for row in rows
            ],
        }

    def lookup_customers(
        self, customer_ids: Annotated[list[str], Field(min_length=1, max_length=20)],
    ) -> dict[str, Any]:
        """Look up customer identifiers in the customer master: status (active, closed or test),
        creation date and notes. Identifiers that do not exist are listed in `not_found`."""
        wanted = list(dict.fromkeys(customer_ids))
        with self._read() as connection:
            rows = connection.execute(
                f"SELECT * FROM customers WHERE customer_id IN ({', '.join('?' * len(wanted))})", wanted,
            ).fetchall()
        found = {row["customer_id"]: row for row in rows}
        return {
            "customers": [
                {"customer_id": cid, "status": found[cid]["status"], "created_at": found[cid]["created_at"],
                 "note": found[cid]["note"]}
                for cid in wanted if cid in found
            ],
            "not_found": [cid for cid in wanted if cid not in found],
        }

    @staticmethod
    def _require(connection: sqlite3.Connection, table: str, column: str, value: str) -> None:
        if connection.execute(f"SELECT 1 FROM {table} WHERE {column} = ?", (value,)).fetchone() is None:
            raise PlatformError(f"Unknown {column.removesuffix('_id').replace('_', ' ')} '{value}'.")


PLATFORM_TOOLS = (
    "get_dataset_contract",
    "list_schema_changes",
    "get_source_status",
    "list_upstream_incidents",
    "lookup_customers",
)


if __name__ == "__main__":
    print(f"Platform database written to {build_platform_database(PLATFORM_DATABASE)}")
