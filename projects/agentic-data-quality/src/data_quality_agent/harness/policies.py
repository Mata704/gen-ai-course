"""When an automatic action may run. Decided in code from stored facts, never by the model.

Each pipeline opts in through `remediation` in its definition file (max retries, quarantine limit).
Whatever an action does, the new attempt goes through every quality rule again before delivery.
"""

from __future__ import annotations

from data_quality_agent.simulator.models import (
    PipelineDefinition,
    PipelineRun,
    PipelineStatus,
    QualityStatus,
    RuleKind,
)

# Source states, as reported by the producing team on the Orders Platform, in which a retry may run.
AVAILABLE_SOURCE_STATUSES = frozenset({"operational", "degraded"})
# Rules about the batch as a whole: holding records back cannot fix them.
BATCH_LEVEL_RULES = frozenset({RuleKind.MIN_ROWS, RuleKind.FRESHNESS})


class PolicyDenied(Exception):
    """The action is not allowed now; the message tells the agent why."""


def check_retry(
    *, incident_kind: str | None, run: PipelineRun, pipeline: PipelineDefinition,
    retries_done: int, source_status: str | None,
) -> None:
    """Retry a failed ingestion only when the source is reported available and within the budget."""
    if incident_kind != "pipeline_failure" or run.pipeline_status != PipelineStatus.FAILED:
        raise PolicyDenied("A retry applies only to a failed pipeline run, not to data that failed the rules.")
    allowed = pipeline.remediation.max_automatic_retries
    if retries_done >= allowed:
        raise PolicyDenied(f"The pipeline allows {allowed} automatic retries per incident; {retries_done} already ran.")
    if source_status is None:
        raise PolicyDenied("The source status could not be read from the Orders Platform.")
    if source_status not in AVAILABLE_SOURCE_STATUSES:
        raise PolicyDenied(f"The Orders Platform reports the source as '{source_status}'; wait until it is available.")


def plan_quarantine(*, run: PipelineRun, pipeline: PipelineDefinition) -> dict[int, list[str]]:
    """Positions of the records to hold back, with the rules each one failed."""
    if run.pipeline_status != PipelineStatus.BLOCKED or run.quality_status != QualityStatus.FAIL:
        raise PolicyDenied("Quarantine applies only to a batch blocked by the quality rules.")
    limit = pipeline.remediation.max_quarantine_fraction
    if limit <= 0:
        raise PolicyDenied(f"Pipeline '{pipeline.pipeline_id}' does not allow quarantine.")
    kinds = {rule.rule_id: rule.kind for rule in pipeline.rules}
    positions: dict[int, list[str]] = {}
    for finding in run.findings:
        if kinds.get(finding.rule_id) in BATCH_LEVEL_RULES or not finding.row_indexes:
            raise PolicyDenied(f"Rule '{finding.rule_id}' concerns the whole batch; holding records back cannot fix it.")
        for index in finding.row_indexes:
            positions.setdefault(index, []).append(finding.rule_id)
    total = len(run.records)
    if not total or len(positions) / total > limit:
        raise PolicyDenied(
            f"{len(positions)} of {total} records failed; the pipeline allows holding back at most {limit:.0%}."
        )
    return positions


def check_failed_record_disposition(*, current_status: str, target_status: str) -> None:
    """Authorize a human-approved disposition without allowing approval to override policy."""
    if current_status != "held":
        raise PolicyDenied("Only a held failed record can be released or discarded.")
    if target_status not in {"released", "discarded"}:
        raise PolicyDenied("A failed record may only be released or discarded.")
