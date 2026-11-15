"""SQLite connection handling and explicit, versioned schema migrations."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DATABASE = Path("runs") / "pipelines.sqlite3"

# Each migration runs once, in order, inside one transaction. Never edit an applied one; add a new one.
MIGRATIONS: list[str] = [
    """
    CREATE TABLE pipelines (
        pipeline_id TEXT NOT NULL,
        version TEXT NOT NULL,
        name TEXT NOT NULL,
        definition_json TEXT NOT NULL,
        registered_at TEXT NOT NULL,
        PRIMARY KEY (pipeline_id, version)
    );
    CREATE TABLE pipeline_runs (
        run_id TEXT PRIMARY KEY,
        pipeline_id TEXT NOT NULL,
        pipeline_version TEXT NOT NULL,
        scenario_id TEXT NOT NULL,
        seed INTEGER NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'blocked', 'failed')),
        quality_status TEXT NOT NULL DEFAULT 'not_run',
        record_count INTEGER NOT NULL DEFAULT 0,
        delay_minutes INTEGER NOT NULL DEFAULT 0,
        observed_columns_json TEXT NOT NULL DEFAULT '[]',
        errors_json TEXT NOT NULL DEFAULT '[]',
        destination TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        FOREIGN KEY (pipeline_id, pipeline_version) REFERENCES pipelines (pipeline_id, version)
    );
    CREATE INDEX pipeline_runs_by_pipeline ON pipeline_runs (pipeline_id, started_at);
    CREATE TABLE run_stages (
        run_id TEXT NOT NULL REFERENCES pipeline_runs (run_id),
        position INTEGER NOT NULL,
        stage TEXT NOT NULL,
        status TEXT NOT NULL,
        PRIMARY KEY (run_id, stage)
    );
    CREATE TABLE run_events (
        run_id TEXT NOT NULL REFERENCES pipeline_runs (run_id),
        sequence INTEGER NOT NULL,
        timestamp TEXT NOT NULL,
        kind TEXT NOT NULL,
        stage TEXT,
        status TEXT,
        level TEXT NOT NULL,
        message TEXT NOT NULL,
        simulation_only INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (run_id, sequence)
    );
    CREATE TABLE run_records (
        run_id TEXT NOT NULL REFERENCES pipeline_runs (run_id),
        step TEXT NOT NULL CHECK (step IN ('ingested', 'transformed')),
        position INTEGER NOT NULL,
        record_json TEXT NOT NULL,
        PRIMARY KEY (run_id, step, position)
    );
    CREATE TABLE quality_findings (
        run_id TEXT NOT NULL REFERENCES pipeline_runs (run_id),
        rule_id TEXT NOT NULL,
        rule_name TEXT NOT NULL,
        severity TEXT NOT NULL,
        message TEXT NOT NULL,
        affected_rows INTEGER NOT NULL,
        row_indexes_json TEXT NOT NULL,
        PRIMARY KEY (run_id, rule_id)
    );
    CREATE TABLE incidents (
        run_id TEXT PRIMARY KEY REFERENCES pipeline_runs (run_id),
        pipeline_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        status TEXT NOT NULL,
        summary TEXT NOT NULL,
        failed_rule_ids_json TEXT NOT NULL,
        opened_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS pipeline_output (
        run_id TEXT NOT NULL,
        pipeline_id TEXT NOT NULL,
        scenario_id TEXT NOT NULL,
        position INTEGER NOT NULL,
        record_json TEXT NOT NULL,
        PRIMARY KEY (run_id, position)
    );
    CREATE TABLE tool_calls (
        call_id INTEGER PRIMARY KEY AUTOINCREMENT,
        called_at TEXT NOT NULL,
        agent TEXT NOT NULL,
        tool TEXT NOT NULL,
        arguments_json TEXT NOT NULL,
        run_id TEXT,
        outcome TEXT NOT NULL CHECK (outcome IN ('ok', 'error', 'blocked')),
        detail TEXT NOT NULL DEFAULT '',
        duration_ms INTEGER NOT NULL
    );
    """,
    # 2: tools now come from two places; NULL is a call to a tool that is not in the catalog.
    """
    ALTER TABLE tool_calls ADD COLUMN source TEXT CHECK (source IN ('local', 'mcp'));
    """,
    # 3: approved data now lives only in the destination file (pipeline_runs.destination).
    """
    DROP TABLE IF EXISTS pipeline_output;
    """,
    # 4: stable incidents, correction attempts and agent investigation history.
    """
    CREATE TABLE incident_workflows (
        incident_id TEXT PRIMARY KEY REFERENCES pipeline_runs (run_id),
        latest_run_id TEXT NOT NULL REFERENCES pipeline_runs (run_id),
        status TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE incident_attempts (
        run_id TEXT PRIMARY KEY REFERENCES pipeline_runs (run_id),
        incident_id TEXT NOT NULL REFERENCES incident_workflows (incident_id),
        correction_reason TEXT
    );
    INSERT INTO incident_workflows
        SELECT run_id, run_id, 'awaiting_correction', opened_at FROM incidents;
    INSERT INTO incident_attempts
        SELECT run_id, run_id, NULL FROM incidents;
    CREATE TABLE agent_sessions (
        session_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES pipeline_runs (run_id),
        status TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        outcome_json TEXT,
        error TEXT
    );
    CREATE UNIQUE INDEX one_active_agent_session ON agent_sessions (run_id) WHERE status = 'running';
    CREATE TABLE agent_steps (
        step_id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL REFERENCES agent_sessions (session_id),
        timestamp TEXT NOT NULL,
        agent TEXT NOT NULL,
        kind TEXT NOT NULL,
        message TEXT NOT NULL
    );
    """,
]


class Database:
    """The local control database (run history, logs, findings, incidents, tool audit).

    The schema is brought up to date when it is opened. Approved data is not stored here.
    """

    def __init__(self, path: str | Path = DEFAULT_DATABASE) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Open a connection, commit on success and roll back on error."""
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                yield connection

    @property
    def schema_version(self) -> int:
        with self.transaction() as connection:
            return connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]

    def _migrate(self) -> None:
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            connection.isolation_level = None
            # WAL lets the UI and the MCP server read while a run is being written.
            connection.execute("PRAGMA journal_mode = WAL")
            # The write lock makes concurrent processes apply each migration only once.
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS schema_migrations "
                    "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
                )
                applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
                for version, script in enumerate(MIGRATIONS, start=1):
                    if version in applied:
                        continue
                    for statement in script.split(";"):
                        if statement.strip():
                            connection.execute(statement)
                    connection.execute(
                        "INSERT INTO schema_migrations VALUES (?, ?)",
                        (version, datetime.now(timezone.utc).isoformat()),
                    )
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
