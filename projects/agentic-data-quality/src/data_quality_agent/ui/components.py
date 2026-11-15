"""Presentation of pipeline progress, history and results."""

from __future__ import annotations

import html
from typing import Any

import streamlit as st

from data_quality_agent.persistence.models import RunSummary
from data_quality_agent.simulator.models import PipelineRun, PipelineStatus
from data_quality_agent.ui.view_model import (
    RUN_BADGES,
    STEP_STATE_LABELS,
    RunTracker,
    StepState,
    format_duration,
    format_log_line,
    run_metrics,
)

SELECTED_KEY = "selected_run"
NEXT_SELECTION_KEY = "next_selected_run"
HISTORY_LIMIT = 50
_EXPANDED_STATES = {StepState.RUNNING, StepState.FAILED, StepState.WAITING}
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


def _local_time(summary: RunSummary) -> str:
    return f"{summary.started_at.astimezone():%d/%m %H:%M:%S}"


def render_history(summaries: list[RunSummary]) -> None:
    st.markdown("#### Execuções")
    if not summaries:
        st.info("Ainda não há execuções. Escolhe um cenário e clica em **Executar pipeline**.")
        return
    statuses = [PipelineStatus(summary.status) for summary in summaries]
    st.caption("  ·  ".join(f"{RUN_BADGES[status]}: **{statuses.count(status)}**" for status in RUN_BADGES))
    by_id = {summary.run_id: summary for summary in summaries}
    # A widget's value can only be changed before it is created in the rerun.
    if NEXT_SELECTION_KEY in st.session_state:
        st.session_state[SELECTED_KEY] = st.session_state.pop(NEXT_SELECTION_KEY)
    if st.session_state.get(SELECTED_KEY) not in by_id:
        st.session_state.pop(SELECTED_KEY, None)
    st.radio(
        "Execução selecionada",
        options=list(by_id),
        key=SELECTED_KEY,
        label_visibility="collapsed",
        format_func=lambda run_id: (
            f"{RUN_BADGES[PipelineStatus(by_id[run_id].status)]} · "
            f"{by_id[run_id].scenario_id} · {_local_time(by_id[run_id])}"
        ),
    )
    if len(summaries) == HISTORY_LIMIT:
        st.caption(f"Mostradas as {HISTORY_LIMIT} execuções mais recentes.")


def render_run(result: PipelineRun, summary: RunSummary, pause: float | None) -> None:
    tracker = RunTracker.from_events(result.events)
    metrics = run_metrics(result)

    st.subheader(f"{RUN_BADGES[result.pipeline_status]} — {result.scenario_id}")
    st.caption(
        f"Execução `{result.run_id}` · pipeline `{result.pipeline_id}` "
        f"(versão `{summary.pipeline_version}`) · iniciada {_local_time(summary)} · "
        f"qualidade `{result.quality_status.value}`"
    )
    if pause:
        st.caption(f"As durações incluem a pausa visual de {pause:.1f} s por etapa iniciada.")

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
