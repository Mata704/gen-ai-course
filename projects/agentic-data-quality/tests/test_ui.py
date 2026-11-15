from pathlib import Path
import json
import sqlite3
from datetime import timedelta

import pytest
from streamlit.testing.v1 import AppTest

from data_quality_agent.persistence import Database, RunRepository
from data_quality_agent.evaluation.storage import EvaluationRepository
from data_quality_agent.persistence.audit import AuditRepository
from data_quality_agent.persistence.models import ModelCall
from data_quality_agent.persistence.telemetry import TelemetryRepository
from data_quality_agent.simulator.engine import DATASETS_DIR, SCENARIOS_DIR, PipelineSimulator
from data_quality_agent.simulator.destination import SQLiteDestination
from data_quality_agent.service import PipelineService
from data_quality_agent.simulator.models import EventKind, PipelineEvent, StageName
from data_quality_agent.ui.view_model import RunTracker, StepState, group_runs, run_metrics

APP_PATH = Path(__file__).parents[1] / "src" / "data_quality_agent" / "ui" / "app.py"


@pytest.fixture
def ui_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path / "runs" / "pipelines.sqlite3"


@pytest.fixture
def simulator(tmp_path: Path) -> PipelineSimulator:
    return PipelineSimulator(warehouse_path=tmp_path / "output.sqlite3")


def test_tracker_shows_the_current_step_while_the_run_is_in_progress(
    simulator: PipelineSimulator,
) -> None:
    tracker = RunTracker()
    snapshots: list[list[StepState]] = []

    def listener(event: PipelineEvent) -> None:
        tracker.apply(event)
        if event.kind == EventKind.STAGE_STARTED and event.stage == StageName.DATA_QUALITY:
            assert tracker.current_step is not None
            assert tracker.current_step.stage == StageName.DATA_QUALITY
            snapshots.append([step.state for step in tracker.steps])

    simulator.run(SCENARIOS_DIR / "quality_issues.json", on_event=listener)

    assert snapshots == [[
        StepState.SUCCEEDED, StepState.SUCCEEDED, StepState.RUNNING,
        StepState.QUEUED, StepState.QUEUED, StepState.QUEUED,
    ]]
    assert tracker.current_step is None
    assert [step.state for step in tracker.steps] == [
        StepState.SUCCEEDED, StepState.SUCCEEDED, StepState.FAILED,
        StepState.WAITING, StepState.SKIPPED, StepState.SKIPPED,
    ]


def test_metrics_summarize_a_blocked_run(simulator: PipelineSimulator) -> None:
    result = simulator.run(SCENARIOS_DIR / "quality_issues.json")

    metrics = run_metrics(result)

    assert metrics.records_received == 41
    assert metrics.records_loaded == 0
    assert metrics.rules_failed == 5
    assert metrics.rows_affected == 5


def test_restarting_agent_analysis_clears_the_previous_stage_end(simulator: PipelineSimulator) -> None:
    result = simulator.run(SCENARIOS_DIR / "quality_issues.json")
    tracker = RunTracker.from_events(result.events)
    tracker.apply(PipelineEvent(
        sequence=len(result.events), run_id=result.run_id, kind=EventKind.STAGE_STARTED,
        stage=StageName.AGENT_INTERVENTION, timestamp=result.events[-1].timestamp + timedelta(seconds=1),
        message="Resume agent investigation.",
    ))
    assert tracker.current_step.stage == StageName.AGENT_INTERVENTION
    assert tracker.current_step.duration_seconds is None


def test_app_runs_selected_scenarios_and_keeps_their_history(ui_database: Path) -> None:
    database = ui_database
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not app.exception

    app.selectbox(key="scenario").select("orders-quality-issues")
    app.button(key="execute_pipeline").click().run()
    app.selectbox(key="scenario").select("healthy-orders")
    app.button(key="execute_pipeline").click().run()

    assert not app.exception
    assert app.subheader[0].value == "✅ Concluída — healthy-orders"
    assert len(app.radio(key="selected_run").options) == 2

    blocked = RunRepository(Database(database)).list_runs(status="blocked")[0]
    app.radio(key="selected_run").set_value(blocked.run_id).run()

    assert app.subheader[0].value == "⛔ Bloqueada — orders-quality-issues"
    assert any("Regras que falharam" in markdown.value for markdown in app.markdown)

    # The history lives in SQLite, so a new browser session sees the same runs.
    fresh = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert len(fresh.radio(key="selected_run").options) == 2
    assert fresh.subheader[0].value == "✅ Concluída — healthy-orders"


def test_frontend_accepts_corrections_for_the_same_incident(ui_database: Path) -> None:
    database = ui_database
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    app.selectbox(key="scenario").select("orders-quality-issues")
    app.button(key="execute_pipeline").click().run()
    service = PipelineService(database)
    original = service.runs.list_runs()[0]
    records = json.loads((DATASETS_DIR / "orders.json").read_text(encoding="utf-8"))
    invalid = [dict(row) for row in records]
    invalid[0]["amount"] = -1

    app.text_area(key=f"corrected_batch_{original.run_id}").set_value(json.dumps(invalid))
    app.text_input(key=f"correction_reason_{original.run_id}").set_value("Primeira correção.")
    next(button for button in app.button if button.label == "Validar e reprocessar correção").click().run()
    latest = service.runs.list_runs()[0]
    assert latest.status == "blocked"
    assert service.incidents.get_for_run(latest.run_id).incident_id == original.run_id

    app.text_area(key=f"corrected_batch_{latest.run_id}").set_value(json.dumps(records))
    app.text_input(key=f"correction_reason_{latest.run_id}").set_value("Valor corrigido.")
    next(button for button in app.button if button.label == "Validar e reprocessar correção").click().run()
    assert not app.exception
    corrected = service.runs.list_runs()[0]
    assert corrected.status == "succeeded"
    assert service.incidents.get_for_run(corrected.run_id).status == "resolved"
    assert len(service.incidents.list_attempts(original.run_id)) == 3
    assert any("Incidente resolvido" in success.value for success in app.success)

    fresh = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert any(original.run_id in caption.value for caption in fresh.caption)
    assert any("Incidente resolvido" in success.value for success in fresh.success)


def test_rule_change_ui_requires_attestation_and_a_second_approver(ui_database: Path) -> None:
    database = ui_database
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    app.selectbox(key="scenario").select("orders-late-low-volume")
    app.button(key="execute_pipeline").click().run()
    incident_id = app.checkbox[0].key.rsplit("_", 1)[1]

    app.text_input(key=f"rule_requester_{incident_id}").set_value("analyst")
    app.text_input(key=f"rule_reason_{incident_id}").set_value("Known partial delivery")
    app.number_input[0].set_value(25)
    request_button = next(button for button in app.form_submit_button if button.label.startswith("Pedir aprova"))
    request_button.click().run()

    service = PipelineService(database)
    assert service.rule_changes.list_for_incident(incident_id) == []
    assert app.error

    app.checkbox(key=f"rule_request_attested_{incident_id}").check()
    next(button for button in app.form_submit_button if button.label.startswith("Pedir aprova")).click().run()
    approval = service.rule_changes.list_for_incident(incident_id)[0]
    assert approval.status == "pending"

    app.text_input(key=f"rule_decider_{approval.approval_id}").set_value("reviewer")
    app.checkbox(key=f"rule_decider_attested_{approval.approval_id}").check()
    next(button for button in app.form_submit_button if button.label.startswith("Aprovar altera")).click().run()

    assert not app.exception
    assert service.rule_changes.list_for_incident(incident_id)[0].status == "executed"
    active_rule = next(
        rule for rule in service.current_pipeline("orders_daily").rules if rule.rule_id == "minimum-volume"
    )
    assert active_rule.minimum_count == 25


def test_ui_accepts_a_custom_batch_and_rejects_invalid_json(ui_database: Path) -> None:
    database = ui_database
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    app.radio(key="input_mode").set_value("Lote próprio").run()
    app.text_area(key="new_batch_json").set_value("{bad")
    app.button(key="execute_pipeline").click().run()
    assert app.error
    assert PipelineService(database).runs.list_runs() == []

    payload = (DATASETS_DIR / "orders.json").read_text(encoding="utf-8")
    app.text_area(key="new_batch_json").set_value(payload)
    app.button(key="execute_pipeline").click().run()

    assert not app.exception
    [summary] = PipelineService(database).runs.list_runs()
    assert (summary.scenario_id, summary.status) == ("user-orders", "succeeded")
    assert len(PipelineService(database).runs.get_output(summary.run_id)) == 40


def test_ui_runs_evaluations_and_loads_persisted_history(ui_database: Path) -> None:
    database = ui_database
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    app.radio(key="workspace_page").set_value("Avaliação").run()
    app.multiselect(key="evaluation_cases").set_value(["healthy-orders"])
    app.button(key="execute_evaluation").click().run()

    assert not app.exception
    [evaluation] = EvaluationRepository(Database(database)).list_reports()
    assert evaluation[1].passed_cases == 1
    assert RunRepository(Database(database)).list_runs() == []
    assert any("Timeline" in markdown.value for markdown in app.markdown)

    fresh = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    fresh.radio(key="workspace_page").set_value("Avaliação").run()
    assert not fresh.exception
    assert fresh.selectbox(key="selected_evaluation").value == evaluation[0]


def test_ui_displays_recorded_tokens_and_filterable_logs(ui_database: Path) -> None:
    database = ui_database
    service = PipelineService(database)
    result = service.run(SCENARIOS_DIR / "healthy.json")
    TelemetryRepository(service.database).record(ModelCall(
        session_id=None, run_id=result.run_id, agent="quality", model_name="offline-example",
        provider="test", started_at=result.events[0].timestamp, duration_ms=150,
        outcome="ok", input_tokens=37, output_tokens=11,
    ))
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()

    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Tokens de entrada"] == "37"
    assert metrics["Tokens de saída"] == "11"
    TelemetryRepository(service.database).record(ModelCall(
        session_id=None, run_id=result.run_id, agent="quality", model_name="offline-example",
        provider="test", started_at=result.events[0].timestamp, duration_ms=200,
        outcome="error", input_tokens=None, output_tokens=None,
    ))
    app.button(key="refresh_workspace").click().run()
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Tokens de entrada"] == "≥ 37"
    assert metrics["Tokens de saída"] == "≥ 11"
    assert metrics["Pedidos com erro"] == "1"
    app.text_input(key=f"log_query_{result.run_id}").set_value("no-matching-event").run()
    assert any("0 de" in caption.value for caption in app.caption)
    app.radio(key="workspace_page").set_value("Observabilidade").run()
    assert not app.exception
    assert app.multiselect(key="metrics_models").options == ["offline-example"]


def test_rule_change_ui_switches_threshold_before_submission(ui_database: Path) -> None:
    database = ui_database
    service = PipelineService(database)
    original = service.run(SCENARIOS_DIR / "late_and_low_volume.json")
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    app.selectbox(key=f"rule_choice_{original.run_id}").select("freshness").run()
    app.number_input[0].set_value(0)
    app.text_input(key=f"rule_requester_{original.run_id}").set_value("analyst")
    app.text_input(key=f"rule_reason_{original.run_id}").set_value("Require a fresh export")
    app.checkbox(key=f"rule_request_attested_{original.run_id}").check()
    next(button for button in app.form_submit_button if button.label.startswith("Pedir aprova")).click().run()

    assert not app.exception
    [request] = service.rule_changes.list_for_incident(original.run_id)
    assert (request.attribute, request.proposed_value) == ("maximum_delay_minutes", 0)


def test_ui_keeps_quarantine_disposition_subject_to_second_person_approval(ui_database: Path) -> None:
    database = ui_database
    service = PipelineService(database)
    original = service.run(SCENARIOS_DIR / "few_invalid_records.json")
    service.incidents.start_session("setup", original.run_id)
    action = service.quarantine_failed_records(original.run_id, requested_by="remediation")
    service.incidents.finish_session("setup", error="Stopped after the action for human review.")
    service.incidents.set_status(original.run_id, "awaiting_correction", run_id=action["new_run_id"])
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    prefix = f"{original.run_id}_{original.run_id}_7"
    app.text_input(key=f"requester_{prefix}").set_value("analyst")
    app.text_input(key=f"request_reason_{prefix}").set_value("Review held row")
    app.checkbox(key=f"request_attested_{prefix}").check()
    next(button for button in app.form_submit_button if button.label == "Pedir aprovação").click().run()
    [request] = service.approvals.list_for_incident(original.run_id)
    app.text_input(key=f"decider_{request.approval_id}").set_value("analyst")
    app.checkbox(key=f"decider_attested_{request.approval_id}").check()
    next(button for button in app.form_submit_button if button.label == "Aprovar e executar").click().run()
    assert service.approvals.list_for_incident(original.run_id)[0].status == "pending"

    app.text_input(key=f"decider_{request.approval_id}").set_value("reviewer")
    next(button for button in app.form_submit_button if button.label == "Aprovar e executar").click().run()
    assert not app.exception
    assert service.approvals.list_for_incident(original.run_id)[0].status == "executed"
    assert service.actions.list_failed_records(original.run_id)[0].status == "released"
    assert len(service.runs.get_output(action["new_run_id"])) == 38


def test_ui_does_not_hide_unfinished_runs_and_their_logs(ui_database: Path) -> None:
    database = ui_database
    service = PipelineService(database)
    run = service.run(SCENARIOS_DIR / "healthy.json")
    with service.database.transaction() as connection:
        connection.execute("UPDATE pipeline_runs SET status = 'running', finished_at = NULL")
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()

    assert not app.exception
    assert app.radio(key="selected_run").value == run.run_id
    assert any("ainda não tem resultado final" in warning.value for warning in app.warning)
    assert any("Timeline" in markdown.value for markdown in app.markdown)


def test_ui_clean_requires_confirmation_and_resets_the_screen(ui_database: Path, tmp_path: Path) -> None:
    database = ui_database
    service = PipelineService(database)
    service.run(SCENARIOS_DIR / "healthy.json")
    other_service = PipelineService(tmp_path / "other" / "control.sqlite3")
    other_run = other_service.run(SCENARIOS_DIR / "healthy.json")
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    app.session_state["database"] = str(other_service.database.path)
    app.run()
    assert len(app.radio(key="selected_run").options) == 1
    assert app.radio(key="selected_run").value != other_run.run_id
    assert not any(widget.key == "database" for widget in app.text_input)
    app.button(key="execute_pipeline").click().run()
    assert len(service.runs.list_runs()) == 2
    assert [run.run_id for run in other_service.runs.list_runs()] == [other_run.run_id]
    assert not any(widget.key == "history_search" for widget in app.text_input)
    assert not any(widget.key in {"history_status", "history_limit"} for widget in app.selectbox)
    assert not app.slider
    assert not any(expander.label == "Configuração" for expander in app.expander)
    app.button(key="clean_workspace").click().run()
    assert len(service.runs.list_runs()) == 2
    app.button(key="cancel_clean_workspace").click().run()
    assert len(service.runs.list_runs()) == 2
    assert not any(button.key == "confirm_clean_workspace" for button in app.button)
    app.session_state["stale_context"] = "Discard this state."
    app.checkbox(key="run_agents").check()
    app.radio(key="workspace_page").set_value("Observabilidade").run()
    app.button(key="clean_workspace").click().run()
    app.button(key="confirm_clean_workspace").click().run()

    assert not app.exception
    assert not app.error
    assert service.runs.list_runs() == []
    assert app.radio(key="workspace_page").value == "Execuções"
    assert app.checkbox(key="run_agents").value is False
    assert app.selectbox(key="scenario").value == "healthy-orders"
    assert "database" not in app.session_state
    assert "stale_context" not in app.session_state
    assert "selected_run" not in app.session_state
    assert not app.metric
    assert not any(button.key == "confirm_clean_workspace" for button in app.button)
    assert [run.run_id for run in other_service.runs.list_runs()] == [other_run.run_id]
    assert other_service.runs.get_output(other_run.run_id)
    app.button(key="execute_pipeline").click().run()
    assert not app.exception
    assert len(service.runs.list_runs()) == 1
    assert app.subheader[0].value == "✅ Concluída — healthy-orders"


def test_ui_reports_clean_failure_without_clearing_session_state(
    ui_database: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = ui_database
    service = PipelineService(database)
    service.run(SCENARIOS_DIR / "healthy.json")
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    app.session_state["stale_context"] = "Retain state on failure."

    def fail_clear(destination: SQLiteDestination) -> None:
        raise sqlite3.OperationalError("Warehouse locked for testing.")

    monkeypatch.setattr(SQLiteDestination, "clear", fail_clear)
    app.button(key="clean_workspace").click().run()
    app.button(key="confirm_clean_workspace").click().run()

    assert not app.exception
    assert any("Warehouse locked for testing." in error.value for error in app.error)
    assert len(service.runs.list_runs()) == 1
    assert app.session_state["stale_context"] == "Retain state on failure."
    assert app.session_state["confirm_clean"] is True


def test_agent_created_attempt_is_inline_and_has_separate_collapsible_telemetry(
    ui_database: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_agents import scripted_model

    monkeypatch.setattr(
        "data_quality_agent.harness.model.configured_model",
        lambda: scripted_model(action="quarantine_failed_records"),
    )
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    app.checkbox(key="run_agents").check()
    app.selectbox(key="scenario").select("orders-few-invalid")
    app.button(key="execute_pipeline").click().run()
    assert not app.exception
    service = PipelineService(ui_database)
    [action] = service.actions.list_actions()
    primary = action.source_run_id
    child = action.result_run_id
    assert child is not None
    assert child != primary
    assert len(service.runs.list_runs()) == 2
    assert len(app.radio(key="selected_run").options) == 1
    assert app.radio(key="selected_run").value == primary
    assert app.subheader[0].value == "✅ Concluída — orders-few-invalid"
    graph = next(markdown.value for markdown in app.markdown if 'aria-label="Tentativa automática 1"' in markdown.value)
    assert graph.index("Intervenção dos agentes") < graph.index('aria-label="Tentativa automática 1"')
    assert graph.index('aria-label="Tentativa automática 1"') < graph.rindex("Ingestão")
    for label in (
        "Agentes e tokens · Tentativa automática 1",
        "Logs e auditoria · Tentativa automática 1",
        "Dados e métricas · Tentativa automática 1",
    ):
        expander = next(expander for expander in app.expander if expander.label == label)
        assert expander.proto.expanded is False
    app.session_state["next_selected_run"] = child
    app.run()
    assert app.radio(key="selected_run").value == primary
    legacy = AppTest.from_file(str(APP_PATH), default_timeout=30)
    legacy.session_state["selected_run"] = child
    legacy.run()
    assert legacy.radio(key="selected_run").value == primary
    summary = service.runs.get_summary(primary)
    assert summary is not None
    for run_id, tokens in ((primary, 101), (child, 17)):
        TelemetryRepository(service.database).record(ModelCall(
            session_id=None, run_id=run_id, agent="reviewer", model_name="measured-test",
            provider="test", started_at=summary.started_at, duration_ms=1, outcome="ok",
            input_tokens=tokens, output_tokens=3,
        ))
    AuditRepository(service.database).record(
        agent="reviewer", tool="get_delivery_status", source="local", arguments={"run_id": child},
        run_id=child, outcome="ok", detail="secondary-only-marker", duration_ms=1,
    )
    totals = {primary: 0, child: 0}
    for call in TelemetryRepository(service.database).list_calls():
        assert call.input_tokens is not None
        totals[call.run_id] += call.input_tokens
    app.button(key="refresh_workspace").click().run()
    agents_tab = next(tab for tab in app.tabs if tab.label == "Agentes e tokens")
    assert agents_tab.metric[0].value == f"{totals[primary]:,}".replace(",", " ")
    child_agents = next(
        expander for expander in agents_tab.expander
        if expander.label == "Agentes e tokens · Tentativa automática 1"
    )
    assert child_agents.metric[0].value == f"{totals[child]:,}".replace(",", " ")
    child_logs = next(
        expander for expander in app.expander
        if expander.label == "Logs e auditoria · Tentativa automática 1"
    )
    rows = child_logs.dataframe[0].value
    assert set(rows["Execução"]) == {child}
    assert any("secondary-only-marker" in message for message in rows["Mensagem"])
    app.text_input(key=f"log_query_{primary}").set_value("secondary-only-marker").run()
    logs_tab = next(tab for tab in app.tabs if tab.label == "Logs e auditoria")
    assert any(caption.value.startswith("0 de") for caption in logs_tab.caption)
    app.session_state["global_log_runs"] = [child]
    app.radio(key="workspace_page").set_value("Observabilidade").run()
    assert not app.exception
    assert app.metric[0].value == f"{sum(totals.values()):,}".replace(",", " ")
    assert len(app.multiselect(key="global_log_runs").options) == 1
    assert app.multiselect(key="global_log_runs").value == [primary]


@pytest.mark.parametrize("status", ["running", "failed"])
def test_unfinished_and_failed_automatic_attempts_stay_in_the_primary_history_item(
    ui_database: Path, status: str,
) -> None:
    service = PipelineService(ui_database)
    primary = service.run(SCENARIOS_DIR / "few_invalid_records.json")
    service.incidents.start_session("setup", primary.run_id)
    action = service.quarantine_failed_records(primary.run_id, requested_by="remediation")
    service.incidents.finish_session("setup", error="Stopped for review.")
    child = action["new_run_id"]
    with service.database.transaction() as connection:
        connection.execute("UPDATE pipeline_runs SET status = ? WHERE run_id = ?", (status, child))
        connection.execute(
            "UPDATE incident_actions SET status = 'running', result_run_id = NULL WHERE result_run_id = ?",
            (child,),
        )
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()

    assert not app.exception
    assert app.radio(key="selected_run").value == primary.run_id
    assert len(app.radio(key="selected_run").options) == 1
    assert app.subheader[0].value.startswith("🟡 Em execução" if status == "running" else "❌ Falhou")
    child_data = next(
        expander for expander in app.expander
        if expander.label == "Dados e métricas · Tentativa automática 1"
    )
    if status == "running":
        assert any("ainda não tem resultado final" in warning.value for warning in child_data.warning)
    assert any('aria-label="Tentativa automática 1"' in markdown.value for markdown in app.markdown)


def test_grouping_keeps_chained_automatic_attempts_but_not_manual_corrections(ui_database: Path) -> None:
    service = PipelineService(ui_database)
    primary = service.run(SCENARIOS_DIR / "few_invalid_records.json")
    service.incidents.start_session("setup", primary.run_id)
    service.quarantine_failed_records(primary.run_id, requested_by="remediation")
    [action] = service.actions.list_actions()
    summaries = service.runs.list_runs(limit=None)
    child = next(summary for summary in summaries if summary.run_id == action.result_run_id)
    grandchild = child.model_copy(update={
        "run_id": "grandchild", "status": "running", "started_at": child.started_at + timedelta(seconds=1),
    })
    manual = child.model_copy(update={"run_id": "manual-correction"})
    second_action = action.model_copy(update={
        "source_run_id": child.run_id, "result_run_id": None, "execution_run_id": grandchild.run_id,
    })

    groups = group_runs([grandchild, manual, *summaries], [second_action, action])

    assert len(groups) == 2
    automatic = next(group for group in groups if group.primary.run_id == primary.run_id)
    assert automatic.run_ids == [primary.run_id, child.run_id, grandchild.run_id]
    assert automatic.status == "running"
    assert next(group for group in groups if group.primary.run_id == manual.run_id).secondary == []
