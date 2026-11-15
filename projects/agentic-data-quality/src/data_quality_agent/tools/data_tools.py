"""Local read-only tools over our SQLite history (runs, findings, incidents) and the runbooks.

These tools run in process. External data (contracts, source status, customer master) comes from
the Orders Platform MCP server instead; both kinds go through the same gateway.

Context policy (course session 02): each tool returns a small, already-filtered view with
evidence refs, never whole batches or every log line. Simulator bookkeeping (scenario names,
injected faults) is not returned, so agents cannot read the answer of a scenario.
"""

# No `from __future__ import annotations`: pydantic's validate_call reads these annotations at runtime.
from collections import Counter
from typing import Annotated, Any

from pydantic import Field

from data_quality_agent.persistence.repository import RunRepository, RunSummary
from data_quality_agent.simulator.models import EventKind, LogLevel, PipelineDefinition, StageName
from data_quality_agent.tools.runbooks import RunbookLibrary

MAX_ROW_INDEXES = 20


class ToolInputError(ValueError):
    """The arguments do not identify anything the tool can answer about."""


class DataQualityTools:
    def __init__(self, runs: RunRepository, runbooks: RunbookLibrary | None = None) -> None:
        self.runs = runs
        self.runbooks = runbooks or RunbookLibrary()

    # Pipeline and run state ------------------------------------------------------------------

    def get_run_summary(self, run_id: str) -> dict[str, Any]:
        """State of one pipeline run: status of each stage, record count, source delay, errors,
        and columns compared with the expected schema. Start here when investigating a run."""
        summary = self._summary(run_id)
        pipeline = self._pipeline(summary)
        expected = set(pipeline.expected_columns)
        observed = set(summary.observed_columns)
        return {
            "run_id": run_id,
            "pipeline_id": summary.pipeline_id,
            "pipeline_version": summary.pipeline_version,
            "source_system": pipeline.source_system,
            "source_dataset": pipeline.source_dataset,
            "status": summary.status,
            "quality_status": summary.quality_status.value,
            "started_at": summary.started_at.isoformat(),
            "finished_at": summary.finished_at.isoformat() if summary.finished_at else None,
            "record_count": summary.record_count,
            "delay_minutes": summary.delay_minutes,
            "stages": [{"stage": stage.name.value, "status": stage.status.value}
                       for stage in self.runs.get_stages(run_id)],
            "errors": summary.errors,
            "missing_columns": sorted(expected - observed) if observed else [],
            "unexpected_columns": sorted(observed - expected),
            "has_incident": self.runs.get_incident(run_id) is not None,
        }

    def get_run_logs(
        self,
        run_id: str,
        stage: StageName | None = None,
        level: LogLevel | None = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
    ) -> dict[str, Any]:
        """Log lines of one run, optionally only one stage and/or one level (info, warning, error).
        Each line has a ref to cite as evidence."""
        self._summary(run_id)
        lines = [
            event for event in self.runs.get_events(run_id, include_simulation=False)
            if event.kind == EventKind.LOG
            and (stage is None or event.stage == stage)
            and (level is None or event.level == level)
        ]
        return {
            "run_id": run_id,
            "matching": len(lines),
            "truncated": len(lines) > limit,
            "lines": [
                {
                    "ref": f"log:{run_id}:{event.sequence}",
                    "time": event.timestamp.isoformat(),
                    "stage": event.stage.value if event.stage else None,
                    "level": event.level.value,
                    "message": event.message,
                }
                for event in lines[:limit]
            ],
        }

    def list_recent_runs(
        self, pipeline_id: str, limit: Annotated[int, Field(ge=1, le=20)] = 10,
    ) -> dict[str, Any]:
        """Most recent runs of a pipeline, newest first, to see whether a failure is new or repeated."""
        runs = self.runs.list_runs(pipeline_id=pipeline_id, limit=limit)
        return {
            "pipeline_id": pipeline_id,
            "runs": [
                {
                    "run_id": run.run_id,
                    "status": run.status,
                    "quality_status": run.quality_status.value,
                    "record_count": run.record_count,
                    "delay_minutes": run.delay_minutes,
                    "started_at": run.started_at.isoformat(),
                }
                for run in runs
            ],
        }

    def compare_with_last_success(self, run_id: str) -> dict[str, Any]:
        """Compare a run with the last successful run of the same pipeline before it:
        record count, source delay and columns added or removed."""
        summary = self._summary(run_id)
        baseline = self.runs.last_successful_run(summary.pipeline_id, before=summary.started_at)
        if baseline is None:
            return {"run_id": run_id, "baseline_run_id": None,
                    "detail": "No earlier successful run of this pipeline."}
        current, previous = set(summary.observed_columns), set(baseline.observed_columns)
        return {
            "run_id": run_id,
            "baseline_run_id": baseline.run_id,
            "record_count": {"current": summary.record_count, "baseline": baseline.record_count},
            "delay_minutes": {"current": summary.delay_minutes, "baseline": baseline.delay_minutes},
            "columns_added": sorted(current - previous),
            "columns_removed": sorted(previous - current) if current else [],
        }

    def get_incident(self, run_id: str) -> dict[str, Any]:
        """The incident opened by a run, if any: kind, status, summary and failed rules."""
        self._summary(run_id)
        incident = self.runs.get_incident(run_id)
        if incident is None:
            return {"run_id": run_id, "incident": None}
        return {
            "run_id": run_id,
            "incident": {
                "ref": f"incident:{run_id}",
                "kind": incident.kind,
                "status": incident.status,
                "summary": incident.summary,
                "failed_rule_ids": incident.failed_rule_ids,
                "opened_at": incident.opened_at.isoformat(),
            },
        }

    def get_delivery_status(self, run_id: str) -> dict[str, Any]:
        """Whether the batch of a run was loaded into the destination and verified by reading it back."""
        summary = self._summary(run_id)
        stage = next((s for s in self.runs.get_stages(run_id) if s.name == StageName.DELIVERY), None)
        loaded = len(self.runs.get_output(run_id))
        return {
            "run_id": run_id,
            "run_status": summary.status,
            "delivery_stage": stage.status.value if stage else None,
            "records_in_batch": summary.record_count,
            "records_loaded": loaded,
            "verified": summary.status == "succeeded" and loaded == summary.record_count,
        }

    # Data quality ----------------------------------------------------------------------------

    def list_quality_rules(self, pipeline_id: str) -> dict[str, Any]:
        """The deterministic quality rules and expected columns of the current pipeline version.
        Each rule says whether it is a general rule (shared by all pipelines, maybe adjusted here,
        with the reason) or the pipeline's own; general rules switched off are listed apart."""
        pipeline = self.runs.get_pipeline(pipeline_id)
        if pipeline is None:
            raise ToolInputError(f"Unknown pipeline '{pipeline_id}'.")
        return {
            "pipeline_id": pipeline_id,
            "source_system": pipeline.source_system,
            "source_dataset": pipeline.source_dataset,
            "expected_columns": pipeline.expected_columns,
            "rules": [
                {**rule.model_dump(mode="json", exclude_defaults=True), "origin": rule.origin}
                for rule in pipeline.rules
            ],
            "disabled_general_rules": pipeline.disabled_general_rules,
        }

    def get_quality_findings(self, run_id: str) -> dict[str, Any]:
        """Rules that failed in a run, with the rule definition, severity and affected row indexes."""
        summary = self._summary(run_id)
        rules = {rule.rule_id: rule for rule in self._pipeline(summary).rules}
        findings = []
        for finding in self.runs.get_findings(run_id):
            rule = rules.get(finding.rule_id)
            findings.append({
                "ref": f"finding:{run_id}:{finding.rule_id}",
                "rule_id": finding.rule_id,
                "rule_name": finding.rule_name,
                "kind": rule.kind.value if rule else None,
                "field": rule.field if rule else None,
                "severity": finding.severity.value,
                "message": finding.message,
                "affected_rows": finding.affected_rows,
                "row_indexes": finding.row_indexes[:MAX_ROW_INDEXES],
            })
        return {
            "run_id": run_id,
            "quality_status": summary.quality_status.value,
            "rules_checked": len(rules) if summary.quality_status.value != "not_run" else 0,
            "failed": findings,
        }

    def get_affected_records(
        self, run_id: str, rule_id: str, limit: Annotated[int, Field(ge=1, le=20)] = 10,
    ) -> dict[str, Any]:
        """Only the records that failed one rule in a run, as checked by the quality gate."""
        self._summary(run_id)
        finding = next((f for f in self.runs.get_findings(run_id) if f.rule_id == rule_id), None)
        if finding is None:
            raise ToolInputError(f"Rule '{rule_id}' did not fail in run '{run_id}'.")
        if not finding.row_indexes:
            return {"run_id": run_id, "rule_id": rule_id, "records": [],
                    "detail": "This rule applies to the whole batch, not to individual records."}
        records = self.runs.get_records(run_id, "transformed")
        return {
            "run_id": run_id,
            "rule_id": rule_id,
            "affected_rows": finding.affected_rows,
            "truncated": len(finding.row_indexes) > limit,
            "records": [
                {"ref": f"record:{run_id}:{index}", "index": index, "record": records[index]}
                for index in finding.row_indexes[:limit]
                if index < len(records)
            ],
        }

    def get_batch_profile(self, run_id: str) -> dict[str, Any]:
        """Column profile of the batch checked by the quality gate: presence, nulls, distinct
        values and value types per column, without returning the records."""
        summary = self._summary(run_id)
        pipeline = self._pipeline(summary)
        records = self.runs.get_records(run_id, "transformed") or self.runs.get_records(run_id, "ingested")
        columns = sorted({column for row in records for column in row} | set(pipeline.expected_columns))
        profile = []
        for column in columns:
            values = [row[column] for row in records if column in row]
            profile.append({
                "column": column,
                "expected": column in pipeline.expected_columns,
                "present_in_rows": len(values),
                "null_count": sum(value is None for value in values),
                "distinct_values": len({repr(value) for value in values if value is not None}),
                "types": dict(Counter(type(value).__name__ for value in values if value is not None)),
            })
        return {"run_id": run_id, "row_count": len(records), "columns": profile}

    # Skills ----------------------------------------------------------------------------------

    def find_runbook(self, run_id: str, rule_id: str | None = None) -> dict[str, Any]:
        """Load the runbook (procedure) that applies to a failed rule of a run, or to the run's
        incident. Without rule_id, a data-quality incident returns the list of applicable runbooks."""
        summary = self._summary(run_id)
        if rule_id is not None:
            rule = next((r for r in self._pipeline(summary).rules if r.rule_id == rule_id), None)
            if rule is None:
                raise ToolInputError(f"Pipeline '{summary.pipeline_id}' has no rule '{rule_id}'.")
            return self._runbook_result(self.runbooks.for_rule_kind(rule.kind.value), f"rule kind '{rule.kind.value}'")

        incident = self.runs.get_incident(run_id)
        if incident is None:
            return {"run_id": run_id, "runbook": None, "detail": "The run has no incident."}
        if incident.kind != "data_quality":
            return self._runbook_result(self.runbooks.for_incident_kind(incident.kind), f"incident '{incident.kind}'")
        rules = {rule.rule_id: rule for rule in self._pipeline(summary).rules}
        applicable = []
        for failed in incident.failed_rule_ids:
            runbook = self.runbooks.for_rule_kind(rules[failed].kind.value) if failed in rules else None
            applicable.append({"rule_id": failed, "runbook": runbook.title if runbook else None})
        return {"run_id": run_id, "applicable": applicable,
                "detail": "Call find_runbook again with a rule_id to load one runbook."}

    # Helpers ---------------------------------------------------------------------------------

    def _summary(self, run_id: str) -> RunSummary:
        summary = self.runs.get_summary(run_id)
        if summary is None:
            raise ToolInputError(f"Unknown run '{run_id}'.")
        return summary

    def _pipeline(self, summary: RunSummary) -> PipelineDefinition:
        pipeline = self.runs.get_pipeline(summary.pipeline_id, summary.pipeline_version)
        if pipeline is None:
            raise ToolInputError(f"Definition of pipeline '{summary.pipeline_id}' is not registered.")
        return pipeline

    @staticmethod
    def _runbook_result(runbook: Any, matched: str) -> dict[str, Any]:
        if runbook is None:
            return {"runbook": None, "detail": f"No runbook applies to {matched}."}
        return {"runbook": {"ref": runbook.ref, "id": runbook.runbook_id, "title": runbook.title,
                            "version": runbook.version, "procedure": runbook.body}}
