from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from data_quality_agent.persistence import Database, RunRepository
from data_quality_agent.simulator.engine import SCENARIOS_DIR, PipelineSimulator
from data_quality_agent.simulator.models import EventKind, PipelineEvent, StageName
from data_quality_agent.ui.view_model import RunTracker, StepState, run_metrics

APP_PATH = Path(__file__).parents[1] / "src" / "data_quality_agent" / "ui" / "app.py"


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

    assert metrics.records_received == 6
    assert metrics.records_loaded == 0
    assert metrics.rules_failed == 5
    assert metrics.rows_affected == 5


def test_app_runs_selected_scenarios_and_keeps_their_history(tmp_path: Path) -> None:
    database = tmp_path / "ui.sqlite3"
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not app.exception
    app.text_input(key="database").set_value(str(database))
    app.slider(key="pause").set_value(0.0)

    app.selectbox(key="scenario").select("orders-quality-issues")
    app.button[0].click().run()
    app.selectbox(key="scenario").select("healthy-orders")
    app.button[0].click().run()

    assert not app.exception
    assert app.subheader[0].value == "✅ Concluída — healthy-orders"
    assert len(app.radio(key="selected_run").options) == 2

    blocked = RunRepository(Database(database)).list_runs(status="blocked")[0]
    app.radio(key="selected_run").set_value(blocked.run_id).run()

    assert app.subheader[0].value == "⛔ Bloqueada — orders-quality-issues"
    assert any("Regras que falharam" in markdown.value for markdown in app.markdown)

    # The history lives in SQLite, so a new browser session sees the same runs.
    fresh = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    fresh.text_input(key="database").set_value(str(database)).run()
    assert len(fresh.radio(key="selected_run").options) == 2
    assert fresh.subheader[0].value == "✅ Concluída — healthy-orders"
