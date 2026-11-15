from pathlib import Path

import pytest

from data_quality_agent.harness.policies import PolicyDenied
from data_quality_agent.service import PipelineService
from data_quality_agent.simulator.engine import SCENARIOS_DIR, load_scenario
from data_quality_agent.simulator.models import FaultKind


def test_approved_bounded_rule_change_applies_only_to_future_runs(tmp_path: Path) -> None:
    service = PipelineService(tmp_path / "history.sqlite3")
    incident = service.run(SCENARIOS_DIR / "late_and_low_volume.json")
    pipeline = service.current_pipeline(incident.pipeline_id)

    approval_id = service.rule_changes.request(
        incident_id=incident.run_id, pipeline=pipeline, rule_id="minimum-volume",
        attribute="minimum_count", proposed_value=25, reason="Allow the known partial export.",
        requested_by="analyst", identity_attested=True,
    )
    with pytest.raises(PolicyDenied, match="different person"):
        service.rule_changes.approve(
            approval_id, pipeline=pipeline, decided_by="analyst", identity_attested=True,
        )
    approved = service.rule_changes.approve(
        approval_id, pipeline=pipeline, decided_by="reviewer", identity_attested=True,
    )

    assert approved.status == "executed"
    active_rule = next(
        rule for rule in service.current_pipeline(incident.pipeline_id).rules if rule.rule_id == "minimum-volume"
    )
    assert active_rule.minimum_count == 25
    scenario = load_scenario(SCENARIOS_DIR / "late_and_low_volume.json")
    scenario = scenario.model_copy(update={
        "faults": [fault for fault in scenario.faults if fault.kind != FaultKind.DELAY],
    })
    next_run = service.run(scenario)
    assert next_run.quality_status.value == "pass"
    assert next_run.record_count == 25
    summary = service.runs.get_summary(next_run.run_id)
    persisted = service.runs.get_pipeline(next_run.pipeline_id, summary.pipeline_version)
    assert next(rule for rule in persisted.rules if rule.rule_id == "minimum-volume").minimum_count == 25


def test_rule_change_policy_restricts_targets_values_and_requires_attestation(tmp_path: Path) -> None:
    service = PipelineService(tmp_path / "history.sqlite3")
    incident = service.run(SCENARIOS_DIR / "late_and_low_volume.json")
    pipeline = service.current_pipeline(incident.pipeline_id)

    with pytest.raises(PolicyDenied, match="Confirm"):
        service.rule_changes.request(
            incident_id=incident.run_id, pipeline=pipeline, rule_id="minimum-volume",
            attribute="minimum_count", proposed_value=20, reason="test", requested_by="analyst",
            identity_attested=False,
        )
    with pytest.raises(PolicyDenied, match="between 1 and 1000"):
        service.rule_changes.request(
            incident_id=incident.run_id, pipeline=pipeline, rule_id="minimum-volume",
            attribute="minimum_count", proposed_value=0, reason="test", requested_by="analyst",
            identity_attested=True,
        )
    with pytest.raises(PolicyDenied, match="Only the minimum-row"):
        service.rule_changes.request(
            incident_id=incident.run_id, pipeline=pipeline, rule_id="valid-amount",
            attribute="minimum_count", proposed_value=20, reason="test", requested_by="analyst",
            identity_attested=True,
        )
