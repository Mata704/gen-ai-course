"""Streamlit page that starts pipeline runs and shows them like CI workflow runs.

Start it with `uv run --locked data-quality-ui`.
"""

from __future__ import annotations

import time
from pathlib import Path

import streamlit as st

from data_quality_agent.persistence.database import DEFAULT_DATABASE, Database
from data_quality_agent.persistence.repository import RunRepository
from data_quality_agent.service import PipelineService
from data_quality_agent.simulator.engine import SCENARIOS_DIR, load_scenario
from data_quality_agent.simulator.models import EventKind, PipelineEvent, Scenario
from data_quality_agent.ui.components import (
    HISTORY_LIMIT,
    NEXT_SELECTION_KEY,
    SELECTED_KEY,
    render_history,
    render_live,
    render_run,
)
from data_quality_agent.ui.view_model import RunTracker

PAUSES_KEY = "pauses"
DEFAULT_SCENARIO = "healthy-orders"


def load_scenarios() -> dict[str, tuple[Path, Scenario]]:
    scenarios = {}
    for path in sorted(SCENARIOS_DIR.glob("*.json")):
        scenario = load_scenario(path)
        scenarios[scenario.scenario_id] = (path, scenario)
    return dict(sorted(scenarios.items(), key=lambda item: item[0] != DEFAULT_SCENARIO))


def execute_run(path: Path, scenario: Scenario, database: str, pause: float) -> None:
    placeholder = st.empty()
    tracker = RunTracker()

    def on_event(event: PipelineEvent) -> None:
        tracker.apply(event)
        render_live(placeholder, tracker, scenario.scenario_id)
        if pause and event.kind == EventKind.STAGE_STARTED:
            time.sleep(pause)

    try:
        result = PipelineService(database).run(path, on_event=on_event)
    except (OSError, ValueError) as error:
        st.error(f"A execução não terminou: {error}")
        return
    st.session_state[PAUSES_KEY][result.run_id] = pause
    st.session_state[NEXT_SELECTION_KEY] = result.run_id
    st.rerun()


def main() -> None:
    st.set_page_config(page_title="Pipeline de Data Quality", page_icon="🧪", layout="wide")
    st.session_state.setdefault(PAUSES_KEY, {})
    scenarios = load_scenarios()

    with st.sidebar:
        st.header("Executar pipeline")
        scenario_id = st.selectbox("Cenário", options=list(scenarios), key="scenario")
        path, scenario = scenarios[scenario_id]
        st.caption(scenario.description)
        if scenario.faults:
            st.caption("Falhas simuladas: " + ", ".join(fault.kind.value for fault in scenario.faults))
        database = st.text_input(
            "Base de controlo SQLite", value=str(DEFAULT_DATABASE), key="database",
            help="Histórico das execuções, logs, findings, incidentes e auditoria. "
            "Os dados aprovados vão para warehouse.sqlite3, na mesma pasta.",
        )
        pause = st.slider(
            "Pausa visual por etapa (s)", 0.0, 2.0, 0.8, 0.1, key="pause",
            help="Só abranda a apresentação para acompanhar a etapa atual; não altera a pipeline.",
        )
        run_clicked = st.button("▶ Executar pipeline", type="primary", width="stretch")

    st.title("Pipeline de Data Quality")
    history, detail = st.columns([1, 3], gap="large")
    runs = RunRepository(Database(database))
    summaries = runs.list_runs(finished_only=True, limit=HISTORY_LIMIT)
    with history:
        render_history(summaries)
    with detail:
        if run_clicked:
            execute_run(path, scenario, database, pause)
        elif summaries:
            selected_id = st.session_state.get(SELECTED_KEY, summaries[0].run_id)
            summary = next(s for s in summaries if s.run_id == selected_id)
            result = runs.get_run(selected_id)
            if result is not None:
                render_run(result, summary, st.session_state[PAUSES_KEY].get(selected_id))


main()
