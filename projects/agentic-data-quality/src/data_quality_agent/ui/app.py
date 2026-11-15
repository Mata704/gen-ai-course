"""Streamlit page that starts pipeline runs and shows them like CI workflow runs.

Start it with `uv run --locked data-quality-ui`.
"""

from __future__ import annotations

import html
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

from data_quality_agent.simulator.destination import DEFAULT_DATABASE
from data_quality_agent.simulator.engine import SCENARIOS_DIR, PipelineSimulator, load_scenario
from data_quality_agent.simulator.models import EventKind, PipelineEvent, PipelineRun, Scenario
from data_quality_agent.ui.view_model import (
    RUN_BADGES,
    STEP_STATE_LABELS,
    RunTracker,
    StepState,
    format_duration,
    format_log_line,
    run_metrics,
)

RUNS_KEY = "runs"
SELECTED_KEY = "selected_run"
NEXT_SELECTION_KEY = "next_selected_run"
DEFAULT_SCENARIO = "healthy-orders"
_EXPANDED_STATES = {StepState.RUNNING, StepState.FAILED, StepState.WAITING}


def load_scenarios() -> dict[str, tuple[Path, Scenario]]:
    scenarios = {}
    for path in sorted(SCENARIOS_DIR.glob("*.json")):
        scenario = load_scenario(path)
        scenarios[scenario.scenario_id] = (path, scenario)
    return dict(sorted(scenarios.items(), key=lambda item: item[0] != DEFAULT_SCENARIO))


_GRAPH_COLORS = {
    StepState.QUEUED: "#8c959f",
    StepState.RUNNING: "#bf8700",
    StepState.SUCCEEDED: "#1a7f37",
    StepState.FAILED: "#cf222e",
    StepState.SKIPPED: "#8c959f",
    StepState.WAITING: "#9a6700",
}


def render_pipeline_graph(tracker: RunTracker) -> None:
    nodes = []
    for step in tracker.steps:
        color = _GRAPH_COLORS[step.state]
        weight = "700" if step.state == StepState.RUNNING else "600"
        duration = format_duration(step.duration_seconds)
        details = STEP_STATE_LABELS[step.state] + (f" · {duration}" if duration else "")
        nodes.append(
            f'<div style="border:1px solid {color};border-left:4px solid {color};border-radius:6px;'
            f'padding:6px 10px;white-space:nowrap;font-size:0.85rem">'
            f'{step.icon} <span style="font-weight:{weight}">{html.escape(step.label)}</span><br>'
            f'<span style="color:{color};font-size:0.75rem">{html.escape(details)}</span></div>'
        )
    arrow = '<div style="color:#8c959f;align-self:center">→</div>'
    st.markdown(
        '<div style="display:flex;flex-wrap:wrap;gap:6px;margin:0.5rem 0 1rem 0">'
        + arrow.join(nodes) + "</div>",
        unsafe_allow_html=True,
    )


def render_steps(tracker: RunTracker) -> None:
    for step in tracker.steps:
        duration = format_duration(step.duration_seconds)
        title = f"{step.icon} {step.label}" + (f" · {duration}" if duration else "")
        with st.expander(title, expanded=step.state in _EXPANDED_STATES):
            if step.logs:
                st.code("\n".join(format_log_line(event) for event in step.logs), language=None)
            else:
                st.caption("Sem registos nesta etapa.")


def render_live(placeholder: Any, tracker: RunTracker, scenario_id: str) -> None:
    with placeholder.container():
        st.subheader(f"🟡 Em execução — {scenario_id}")
        current = tracker.current_step
        st.caption(f"Etapa atual: **{current.label}**" if current else "A concluir a execução…")
        render_pipeline_graph(tracker)
        render_steps(tracker)


def execute_run(path: Path, scenario: Scenario, database: str, pause: float) -> None:
    placeholder = st.empty()
    tracker = RunTracker()

    def on_event(event: PipelineEvent) -> None:
        tracker.apply(event)
        render_live(placeholder, tracker, scenario.scenario_id)
        if pause and event.kind == EventKind.STAGE_STARTED:
            time.sleep(pause)

    started = datetime.now()
    try:
        result = PipelineSimulator(database_path=database).run(path, on_event=on_event)
    except (OSError, ValueError) as error:
        st.error(f"A execução não terminou: {error}")
        return
    st.session_state[RUNS_KEY].insert(0, {"result": result, "pause": pause, "started": started})
    st.session_state[NEXT_SELECTION_KEY] = result.run_id
    st.rerun()


def render_history(runs: list[dict[str, Any]]) -> None:
    st.markdown("#### Execuções")
    if not runs:
        st.info("Ainda não há execuções. Escolhe um cenário e clica em **Executar pipeline**.")
        return
    statuses = [entry["result"].pipeline_status for entry in runs]
    st.caption("  ·  ".join(f"{RUN_BADGES[status]}: **{statuses.count(status)}**" for status in RUN_BADGES))
    by_id = {entry["result"].run_id: entry for entry in runs}
    # A widget's value can only be changed before it is created in the rerun.
    if NEXT_SELECTION_KEY in st.session_state:
        st.session_state[SELECTED_KEY] = st.session_state.pop(NEXT_SELECTION_KEY)
    st.radio(
        "Execução selecionada",
        options=list(by_id),
        key=SELECTED_KEY,
        label_visibility="collapsed",
        format_func=lambda run_id: (
            f"{RUN_BADGES[by_id[run_id]['result'].pipeline_status]} · "
            f"{by_id[run_id]['result'].scenario_id} · {by_id[run_id]['started']:%H:%M:%S}"
        ),
    )


def render_run(entry: dict[str, Any]) -> None:
    result: PipelineRun = entry["result"]
    tracker = RunTracker.from_events(result.events)
    metrics = run_metrics(result)

    st.subheader(f"{RUN_BADGES[result.pipeline_status]} — {result.scenario_id}")
    st.caption(
        f"Execução `{result.run_id}` · pipeline `{result.pipeline_id}` · "
        f"iniciada às {entry['started']:%H:%M:%S} · qualidade `{result.quality_status.value}`"
    )
    if entry["pause"]:
        st.caption(f"As durações incluem a pausa visual de {entry['pause']:.1f} s por etapa iniciada.")

    cards = [*st.columns(3), *st.columns(3)]
    cards[0].metric("Registos recebidos", metrics.records_received)
    cards[1].metric("Registos carregados", metrics.records_loaded)
    cards[2].metric("Duração", format_duration(metrics.duration_seconds) or "0 ms")
    cards[3].metric("Regras falhadas", metrics.rules_failed)
    cards[4].metric("Linhas afetadas", metrics.rows_affected)
    cards[5].metric("Atraso (min)", metrics.delay_minutes)

    render_pipeline_graph(tracker)
    if result.incident is not None:
        st.warning(f"Incidente `{result.incident.kind}` à espera de análise: {result.incident.summary}")
    for error in result.errors:
        st.error(error)

    st.markdown("#### Etapas e logs")
    render_steps(tracker)

    if result.findings:
        st.markdown("#### Regras que falharam")
        st.dataframe(
            [
                {
                    "Regra": finding.rule_id,
                    "Nome": finding.rule_name,
                    "Severidade": finding.severity.value,
                    "Linhas afetadas": finding.affected_rows,
                    "Índices": ", ".join(map(str, finding.row_indexes)),
                    "Mensagem": finding.message,
                }
                for finding in result.findings
            ],
            hide_index=True,
            width="stretch",
        )

    with st.expander("Dados do lote"):
        received, transformed, loaded = st.tabs(["Recebidos", "Transformados", "Carregados"])
        for tab, records in (
            (received, result.input_records),
            (transformed, result.records),
            (loaded, result.output_records),
        ):
            with tab:
                if records:
                    st.dataframe(records, hide_index=True, width="stretch")
                else:
                    st.caption("Sem registos.")


def main() -> None:
    st.set_page_config(page_title="Pipeline de Data Quality", page_icon="🧪", layout="wide")
    st.session_state.setdefault(RUNS_KEY, [])
    scenarios = load_scenarios()

    with st.sidebar:
        st.header("Executar pipeline")
        scenario_id = st.selectbox("Cenário", options=list(scenarios), key="scenario")
        path, scenario = scenarios[scenario_id]
        st.caption(scenario.description)
        if scenario.faults:
            st.caption("Falhas simuladas: " + ", ".join(fault.kind.value for fault in scenario.faults))
        database = st.text_input("Destino SQLite", value=str(DEFAULT_DATABASE), key="database")
        pause = st.slider(
            "Pausa visual por etapa (s)", 0.0, 2.0, 0.8, 0.1, key="pause",
            help="Só abranda a apresentação para acompanhar a etapa atual; não altera a pipeline.",
        )
        run_clicked = st.button("▶ Executar pipeline", type="primary", width="stretch")

    st.title("Pipeline de Data Quality")
    history, detail = st.columns([1, 3], gap="large")
    runs = st.session_state[RUNS_KEY]
    with history:
        render_history(runs)
    with detail:
        if run_clicked:
            execute_run(path, scenario, database, pause)
        elif runs:
            selected = next(
                (entry for entry in runs if entry["result"].run_id == st.session_state.get(SELECTED_KEY)),
                runs[0],
            )
            render_run(selected)


main()
