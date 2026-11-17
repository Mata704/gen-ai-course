"""Recovery is confirmed by deterministic state, not by an agent's conclusion."""

from __future__ import annotations

from data_quality_agent.harness.orchestrator import OrchestrationResult
from data_quality_agent.simulator.models import PipelineRun, PipelineStatus, QualityStatus


def recovery_verified(run: PipelineRun | None) -> bool:
    """The deterministic recovery criterion: all rules passed and the delivery was read back intact."""
    return bool(
        run is not None
        and run.pipeline_status == PipelineStatus.SUCCEEDED
        and run.quality_status == QualityStatus.PASS
        and not run.findings
        and run.output_records == run.records
    )


def confirm_recovery(outcome: OrchestrationResult, run: PipelineRun) -> OrchestrationResult:
    """Final service hook, after orchestration and before persisting the incident outcome."""
    if not recovery_verified(run):
        if outcome.status == "resolved":
            raise ValueError(
                f"Orchestrator returned resolved for {run.run_id}, "
                "but deterministic recovery verification failed."
            )
        return outcome
    return outcome.model_copy(update={
        "status": "resolved",
        "summary": "Recuperação confirmada por código: qualidade aprovada e entrega verificada.",
        "next_step": "Nenhuma correção adicional necessária.",
    })
