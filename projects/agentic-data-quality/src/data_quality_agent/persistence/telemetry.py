"""Model request metadata only: no prompts, responses, credentials or monetary prices."""

from data_quality_agent.persistence.database import Database
from data_quality_agent.persistence.models import ModelCall


class TelemetryRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def record(self, call: ModelCall) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO model_calls (session_id, run_id, agent, model_name, provider, started_at, "
                "duration_ms, outcome, input_tokens, output_tokens) "
                "VALUES (:session_id, :run_id, :agent, :model_name, :provider, :started_at, "
                ":duration_ms, :outcome, :input_tokens, :output_tokens)",
                call.model_dump(mode="json", exclude={"call_id"}),
            )

    def list_calls(self, *, run_ids: list[str] | None = None) -> list[ModelCall]:
        if run_ids == []:
            return []
        query = "SELECT * FROM model_calls"
        params: list[str] = []
        if run_ids is not None:
            query += " WHERE run_id IN (" + ", ".join("?" for _ in run_ids) + ")"
            params = run_ids
        with self.database.transaction() as connection:
            rows = connection.execute(query + " ORDER BY call_id", params).fetchall()
        return [ModelCall.model_validate(dict(row)) for row in rows]
