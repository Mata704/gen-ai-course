"""Typed, parameterized access to run history and incidents."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from data_quality_agent.persistence.audit import AuditRepository as AuditRepository
from data_quality_agent.persistence.database import Database
from data_quality_agent.persistence.models import (
    RecordStep as RecordStep,
    RunState as RunState,
    RunSummary as RunSummary,
    StoredIncident as StoredIncident,
    ToolCall as ToolCall,
)
from data_quality_agent.simulator.destination import SQLiteDestination
from data_quality_agent.simulator.models import (
    EventKind,
    LogLevel,
    PipelineDefinition,
    PipelineEvent,
    PipelineIncident,
    PipelineRun,
    PipelineStatus,
    QualityFinding,
    QualityStatus,
    Severity,
    StageName,
    StageResult,
    StageStatus,
)

def definition_version(definition: PipelineDefinition) -> str:
    """Content hash, so each run points at the exact rules it was checked against."""
    return hashlib.sha256(definition.model_dump_json().encode()).hexdigest()[:12]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    # Pipelines -------------------------------------------------------------------------------

    def register_pipeline(self, definition: PipelineDefinition) -> str:
        version = definition_version(definition)
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO pipelines VALUES (?, ?, ?, ?, ?) ON CONFLICT (pipeline_id, version) "
                "DO UPDATE SET registered_at = excluded.registered_at",
                (definition.pipeline_id, version, definition.name, definition.model_dump_json(), _now()),
            )
        return version

    def get_pipeline(self, pipeline_id: str, version: str | None = None) -> PipelineDefinition | None:
        """The given version, or the most recently registered one."""
        query = "SELECT definition_json FROM pipelines WHERE pipeline_id = ?"
        params: tuple[Any, ...] = (pipeline_id,)
        if version is not None:
            query += " AND version = ?"
            params += (version,)
        with self.database.transaction() as connection:
            row = connection.execute(query + " ORDER BY registered_at DESC LIMIT 1", params).fetchone()
        return PipelineDefinition.model_validate_json(row[0]) if row else None

    # Writing a run ---------------------------------------------------------------------------

    def start_run(
        self,
        *,
        run_id: str,
        pipeline_id: str,
        pipeline_version: str,
        scenario_id: str,
        seed: int,
        destination: str,
        started_at: datetime,
    ) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO pipeline_runs (run_id, pipeline_id, pipeline_version, scenario_id, seed, "
                "status, destination, started_at) VALUES (?, ?, ?, ?, ?, 'running', ?, ?)",
                (run_id, pipeline_id, pipeline_version, scenario_id, seed, destination, started_at.isoformat()),
            )

    def append_event(self, event: PipelineEvent) -> None:
        with self.database.transaction() as connection:
            self._insert_events(connection, [event])

    def finish_run(self, result: PipelineRun) -> None:
        """Store the outcome, the batch snapshots, findings and incident in one transaction."""
        with self.database.transaction() as connection:
            self._insert_events(connection, result.events)
            connection.execute(
                "UPDATE pipeline_runs SET status = ?, quality_status = ?, record_count = ?, "
                "delay_minutes = ?, observed_columns_json = ?, errors_json = ?, finished_at = ? "
                "WHERE run_id = ?",
                (
                    result.pipeline_status.value,
                    result.quality_status.value,
                    result.record_count,
                    result.delay_minutes,
                    json.dumps(result.observed_columns),
                    json.dumps(result.errors),
                    self._finished_at(result.events),
                    result.run_id,
                ),
            )
            self._insert_stages(connection, result.run_id, [(stage.name, stage.status) for stage in result.stages])
            for step, records in (("ingested", result.input_records), ("transformed", result.records)):
                connection.executemany(
                    "INSERT OR REPLACE INTO run_records VALUES (?, ?, ?, ?)",
                    [
                        (result.run_id, step, index, json.dumps(record, allow_nan=False))
                        for index, record in enumerate(records)
                    ],
                )
            connection.executemany(
                "INSERT OR REPLACE INTO quality_findings VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        result.run_id, finding.rule_id, finding.rule_name, finding.severity.value,
                        finding.message, finding.affected_rows, json.dumps(finding.row_indexes),
                    )
                    for finding in result.findings
                ],
            )
            if result.incident is not None:
                incident = result.incident
                connection.execute(
                    "INSERT OR REPLACE INTO incidents VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        incident.run_id, incident.pipeline_id, incident.kind, incident.status,
                        incident.summary, json.dumps(incident.failed_rule_ids), self._finished_at(result.events),
                    ),
                )

    def fail_run(self, run_id: str, error: str) -> None:
        """Close a run that stopped with an unexpected error; stages come from its stored events."""
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT stage, status FROM run_events WHERE run_id = ? AND kind = ? ORDER BY sequence",
                (run_id, EventKind.STAGE_FINISHED.value),
            ).fetchall()
            finished = {StageName(row["stage"]): StageStatus(row["status"]) for row in rows}
            last = connection.execute(
                "SELECT MAX(timestamp) FROM run_events WHERE run_id = ?", (run_id,),
            ).fetchone()[0]
            connection.execute(
                "UPDATE pipeline_runs SET status = 'failed', errors_json = ?, finished_at = ? WHERE run_id = ?",
                (json.dumps([error]), last or _now(), run_id),
            )
            self._insert_stages(
                connection, run_id, [(stage, finished.get(stage, StageStatus.SKIPPED)) for stage in StageName],
            )

    # Reading ---------------------------------------------------------------------------------

    def list_runs(
        self,
        *,
        pipeline_id: str | None = None,
        status: RunState | None = None,
        finished_only: bool = False,
        limit: int = 50,
    ) -> list[RunSummary]:
        clauses, params = [], []
        if pipeline_id is not None:
            clauses.append("pipeline_id = ?")
            params.append(pipeline_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if finished_only:
            clauses.append("status != 'running'")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.database.transaction() as connection:
            rows = connection.execute(
                f"SELECT * FROM pipeline_runs {where} ORDER BY started_at DESC, rowid DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [self._summary(row) for row in rows]

    def get_summary(self, run_id: str) -> RunSummary | None:
        with self.database.transaction() as connection:
            row = connection.execute("SELECT * FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()
        return self._summary(row) if row else None

    def last_successful_run(self, pipeline_id: str, before: datetime) -> RunSummary | None:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM pipeline_runs WHERE pipeline_id = ? AND status = 'succeeded' "
                "AND started_at < ? ORDER BY started_at DESC LIMIT 1",
                (pipeline_id, before.isoformat()),
            ).fetchone()
        return self._summary(row) if row else None

    def get_stages(self, run_id: str) -> list[StageResult]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT stage, status FROM run_stages WHERE run_id = ? ORDER BY position", (run_id,),
            ).fetchall()
        return [StageResult(name=StageName(row["stage"]), status=StageStatus(row["status"])) for row in rows]

    def get_events(self, run_id: str, *, include_simulation: bool = True) -> list[PipelineEvent]:
        query = "SELECT * FROM run_events WHERE run_id = ?"
        if not include_simulation:
            query += " AND simulation_only = 0"
        with self.database.transaction() as connection:
            rows = connection.execute(query + " ORDER BY sequence", (run_id,)).fetchall()
        return [
            PipelineEvent(
                sequence=row["sequence"],
                run_id=row["run_id"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                kind=EventKind(row["kind"]),
                stage=StageName(row["stage"]) if row["stage"] else None,
                status=StageStatus(row["status"]) if row["status"] else None,
                level=LogLevel(row["level"]),
                message=row["message"],
                simulation_only=bool(row["simulation_only"]),
            )
            for row in rows
        ]

    def get_records(self, run_id: str, step: RecordStep) -> list[dict[str, Any]]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT record_json FROM run_records WHERE run_id = ? AND step = ? ORDER BY position",
                (run_id, step),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def get_output(self, run_id: str) -> list[dict[str, Any]]:
        """Records the run delivered, read from the destination file recorded for that run."""
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT destination FROM pipeline_runs WHERE run_id = ?", (run_id,),
            ).fetchone()
        return SQLiteDestination(row["destination"]).read(run_id) if row else []

    def get_findings(self, run_id: str) -> list[QualityFinding]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM quality_findings WHERE run_id = ? ORDER BY rowid", (run_id,),
            ).fetchall()
        return [
            QualityFinding(
                rule_id=row["rule_id"],
                rule_name=row["rule_name"],
                severity=Severity(row["severity"]),
                message=row["message"],
                affected_rows=row["affected_rows"],
                row_indexes=json.loads(row["row_indexes_json"]),
            )
            for row in rows
        ]

    def get_incident(self, run_id: str) -> StoredIncident | None:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT i.*, r.scenario_id FROM incidents i JOIN pipeline_runs r USING (run_id) "
                "WHERE i.run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return StoredIncident(
            run_id=row["run_id"],
            scenario_id=row["scenario_id"],
            pipeline_id=row["pipeline_id"],
            kind=row["kind"],
            status=row["status"],
            summary=row["summary"],
            failed_rule_ids=json.loads(row["failed_rule_ids_json"]),
            opened_at=datetime.fromisoformat(row["opened_at"]),
        )

    def get_run(self, run_id: str) -> PipelineRun | None:
        """Rebuild a finished run exactly as the simulator returned it."""
        summary = self.get_summary(run_id)
        if summary is None or summary.status == "running":
            return None
        incident = self.get_incident(run_id)
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT seed, destination FROM pipeline_runs WHERE run_id = ?", (run_id,),
            ).fetchone()
        return PipelineRun(
            run_id=summary.run_id,
            scenario_id=summary.scenario_id,
            pipeline_id=summary.pipeline_id,
            seed=row["seed"],
            pipeline_status=PipelineStatus(summary.status),
            quality_status=summary.quality_status,
            record_count=summary.record_count,
            delay_minutes=summary.delay_minutes,
            observed_columns=summary.observed_columns,
            findings=self.get_findings(run_id),
            errors=summary.errors,
            records=self.get_records(run_id, "transformed"),
            input_records=self.get_records(run_id, "ingested"),
            stages=self.get_stages(run_id),
            destination=row["destination"],
            output_records=self.get_output(run_id),
            incident=PipelineIncident(**incident.model_dump(exclude={"opened_at"})) if incident else None,
            events=self.get_events(run_id),
        )

    # Helpers ---------------------------------------------------------------------------------

    @staticmethod
    def _insert_events(connection: sqlite3.Connection, events: list[PipelineEvent]) -> None:
        connection.executemany(
            "INSERT OR IGNORE INTO run_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    event.run_id, event.sequence, event.timestamp.isoformat(), event.kind.value,
                    event.stage.value if event.stage else None,
                    event.status.value if event.status else None,
                    event.level.value, event.message, int(event.simulation_only),
                )
                for event in events
            ],
        )

    @staticmethod
    def _insert_stages(
        connection: sqlite3.Connection, run_id: str, stages: list[tuple[StageName, StageStatus]],
    ) -> None:
        order = list(StageName)
        connection.executemany(
            "INSERT OR REPLACE INTO run_stages VALUES (?, ?, ?, ?)",
            [(run_id, order.index(stage), stage.value, status.value) for stage, status in stages],
        )

    @staticmethod
    def _finished_at(events: list[PipelineEvent]) -> str:
        return events[-1].timestamp.isoformat() if events else _now()

    @staticmethod
    def _summary(row: sqlite3.Row) -> RunSummary:
        return RunSummary(
            run_id=row["run_id"],
            pipeline_id=row["pipeline_id"],
            pipeline_version=row["pipeline_version"],
            scenario_id=row["scenario_id"],
            status=row["status"],
            quality_status=QualityStatus(row["quality_status"]),
            record_count=row["record_count"],
            delay_minutes=row["delay_minutes"],
            observed_columns=json.loads(row["observed_columns_json"]),
            errors=json.loads(row["errors_json"]),
            started_at=datetime.fromisoformat(row["started_at"]),
            finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
        )
