"""Independent reviewer: recovery is confirmed by code, not by the agents' conclusions."""

from __future__ import annotations

from data_quality_agent.harness.specialists import Observed, SpecialistReport
from data_quality_agent.simulator.models import PipelineRun, PipelineStatus, QualityStatus

ROLE = "reviewer"

INSTRUCTIONS = """\
You are the independent reviewer. Read get_quality_findings and get_delivery_status for the current
attempt; do not trust the other agents' conclusions. recovery_confirmed can only be true if the
deterministic checks passed, the pipeline succeeded and the delivered records were read back and
verified. Otherwise report the unresolved conditions.
"""

TOOLS = (
    "get_quality_findings",
    "get_run_summary",
    "get_delivery_status",
    "get_relevant_memory",
    # Orders Platform (MCP)
    "get_dataset_contract",
)

# The reviewer must have read these before it may confirm recovery.
REQUIRED_FOR_RECOVERY = {"get_quality_findings", "get_delivery_status"}


def recovery_verified(run: PipelineRun | None) -> bool:
    """The deterministic recovery criterion: all rules passed and the delivery was read back intact."""
    return bool(
        run is not None
        and run.pipeline_status == PipelineStatus.SUCCEEDED
        and run.quality_status == QualityStatus.PASS
        and not run.findings
        and run.output_records == run.records
    )


def check_recovery(report: SpecialistReport, observed: Observed, current_run: PipelineRun | None) -> str | None:
    """Output validator: a report that confirms recovery is accepted only if the state confirms it."""
    if not report.recovery_confirmed:
        return None
    if not recovery_verified(current_run):
        return "Recovery is not confirmed by the deterministic state."
    if not REQUIRED_FOR_RECOVERY <= observed.tools:
        return "Read the quality findings and delivery status before confirming recovery."
    return None
