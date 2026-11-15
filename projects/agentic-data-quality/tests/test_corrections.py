import json
from pathlib import Path

import pytest

from data_quality_agent.corrections import parse_corrected_batch
from data_quality_agent.service import PipelineService
from data_quality_agent.simulator.engine import DATASETS_DIR, SCENARIOS_DIR


def test_corrections_preserve_the_incident_history_and_original_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = PipelineService(tmp_path / "history.sqlite3")
    original = service.run(SCENARIOS_DIR / "quality_issues.json")
    original_summary = service.runs.get_summary(original.run_id)
    records = json.loads((DATASETS_DIR / "orders.json").read_text(encoding="utf-8"))
    bad = [dict(row) for row in records]
    bad[0]["amount"] = -1
    monkeypatch.setattr("data_quality_agent.service.load_pipeline",
                        lambda pipeline_id: pytest.fail("Corrections must use the stored original rules."))
    rejected = service.correct(original.run_id, json.dumps(bad), "Primeira tentativa.")
    assert rejected.pipeline_status.value == "blocked"
    assert {finding.rule_id for finding in rejected.findings} == {"valid-amount"}
    assert service.incidents.get_for_run(rejected.run_id).incident_id == original.run_id

    corrected = service.correct(rejected.run_id, json.dumps(records), "Valor corrigido.")
    workflow = service.incidents.get_for_run(corrected.run_id)
    assert workflow.incident_id == original.run_id
    assert workflow.status == "resolved"
    assert corrected.output_records == records
    assert service.runs.get_run(original.run_id) == original
    assert service.runs.get_summary(corrected.run_id).pipeline_version == original_summary.pipeline_version
    assert [attempt.run_id for attempt in service.incidents.list_attempts(original.run_id)] == [
        original.run_id, rejected.run_id, corrected.run_id,
    ]
    assert service.runs.get_output(original.run_id) == service.runs.get_output(rejected.run_id) == []
    with pytest.raises(ValueError, match="já foi carregado"):
        service.correct(corrected.run_id, json.dumps(records), "Não duplicar a entrega.")


@pytest.mark.parametrize("payload", ["{}", "[1]", "{bad", '[{"amount": NaN}]', '[{"amount": 1e999}]'])
def test_malformed_correction_does_not_create_an_attempt(tmp_path: Path, payload: str) -> None:
    service = PipelineService(tmp_path / "history.sqlite3")
    original = service.run(SCENARIOS_DIR / "source_unavailable.json")
    with pytest.raises(ValueError):
        service.correct(original.run_id, payload, "Correção.")
    assert len(service.runs.list_runs()) == 1
    assert service.incidents.get_for_run(original.run_id).status == "awaiting_correction"


def test_source_failure_can_receive_a_new_batch_without_reinjecting_the_fault(tmp_path: Path) -> None:
    service = PipelineService(tmp_path / "history.sqlite3")
    original = service.run(SCENARIOS_DIR / "source_unavailable.json")
    payload = (DATASETS_DIR / "orders.json").read_text(encoding="utf-8")
    corrected = service.correct(original.run_id, payload, "Origem recuperou.")
    assert corrected.pipeline_status.value == "succeeded"
    assert corrected.errors == []
    assert service.incidents.get_for_run(corrected.run_id).incident_id == original.run_id


def test_correction_from_a_new_service_keeps_the_original_destination(tmp_path: Path) -> None:
    database, warehouse = tmp_path / "history.sqlite3", tmp_path / "approved.sqlite3"
    original = PipelineService(database, warehouse_path=warehouse).run(SCENARIOS_DIR / "quality_issues.json")
    payload = (DATASETS_DIR / "orders.json").read_text(encoding="utf-8")
    corrected = PipelineService(database).correct(original.run_id, payload, "Reenvio da origem.")
    assert corrected.destination == original.destination
    assert corrected.output_records == json.loads(payload)
    assert warehouse.is_file()
    assert not (tmp_path / "warehouse.sqlite3").exists()


def test_empty_batch_stays_blocked_and_stale_attempts_are_rejected(tmp_path: Path) -> None:
    service = PipelineService(tmp_path / "history.sqlite3")
    original = service.run(SCENARIOS_DIR / "source_unavailable.json")
    empty = service.correct(original.run_id, "[]", "Origem enviou lote vazio.")
    assert empty.pipeline_status.value == "blocked"
    assert service.incidents.get_for_run(empty.run_id).status == "awaiting_correction"
    with pytest.raises(ValueError, match="mais recente"):
        service.correct(original.run_id, "[]", "Tentativa desatualizada.")
    service.incidents.claim_correction(service.incidents.get_for_run(empty.run_id))
    with pytest.raises(ValueError, match="em processamento"):
        service.correct(empty.run_id, "[]", "Não iniciar duas correções.")


def test_batch_size_limit_is_enforced() -> None:
    with pytest.raises(ValueError, match="1 MB"):
        parse_corrected_batch(json.dumps([{"text": "x" * 1_000_000}]))
