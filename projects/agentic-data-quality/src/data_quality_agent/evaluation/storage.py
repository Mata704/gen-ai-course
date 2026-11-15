"""Evaluation history in the selected control database; case data stays isolated."""

from uuid import uuid4

from data_quality_agent.evaluation.models import EvaluationReport
from data_quality_agent.persistence.database import Database


class EvaluationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def save(self, report: EvaluationReport) -> str:
        evaluation_id = str(uuid4())
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO evaluation_reports VALUES (?, ?, ?)",
                (evaluation_id, report.started_at.isoformat(), report.model_dump_json()),
            )
        return evaluation_id

    def list_reports(self) -> list[tuple[str, EvaluationReport]]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT evaluation_id, report_json FROM evaluation_reports ORDER BY started_at DESC, rowid DESC",
            ).fetchall()
        return [
            (row["evaluation_id"], EvaluationReport.model_validate_json(row["report_json"]))
            for row in rows
        ]
