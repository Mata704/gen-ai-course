"""Presentation of pipeline progress, history and results."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING, Any

import streamlit as st

from data_quality_agent.persistence.models import RunSummary
from data_quality_agent.simulator.models import PipelineRun, StageName
from data_quality_agent.ui.view_model import (
    RUN_BADGES,
    STEP_STATE_LABELS,
    RunTracker,
    RunGroup,
    StepView,
    StepState,
    format_duration,
    format_log_line,
    run_metrics,
    group_runs,
)

if TYPE_CHECKING:
    from data_quality_agent.service import PipelineService

SELECTED_KEY = "selected_run"
NEXT_SELECTION_KEY = "next_selected_run"
_HISTORY_BADGES = {status.value: label for status, label in RUN_BADGES.items()}
_HISTORY_BADGES["running"] = "🟡 Em execução"
_EXPANDED_STATES = {StepState.RUNNING, StepState.FAILED, StepState.WAITING}
_GRAPH_COLORS = {
    StepState.QUEUED: "#8c959f",
    StepState.RUNNING: "#bf8700",
    StepState.SUCCEEDED: "#1a7f37",
    StepState.FAILED: "#cf222e",
    StepState.SKIPPED: "#8c959f",
    StepState.WAITING: "#9a6700",
}


def apply_theme() -> None:
    st.markdown(
        """<style>
        .block-container { max-width: 1500px; padding-top: 2rem; }
        h1 { letter-spacing: -0.045em; }
        [data-testid="stMetric"] {
            border: 1px solid color-mix(in srgb, currentColor 12%, transparent);
            border-radius: 8px; padding: 6px 10px;
            background: color-mix(in srgb, var(--secondary-background-color) 65%, transparent);
        }
        [data-testid="stMetricValue"] {
            font-variant-numeric: tabular-nums; font-size: 1.35rem; line-height: 1.3;
        }
        [data-testid="stMetricLabel"] p { font-size: .78rem; }
        [data-baseweb="tab-list"] { gap: 1rem; }
        [data-baseweb="tab"] { padding: .6rem .3rem; }
        div[data-testid="stExpander"] { border-radius: 12px; }
        .studio-label { color: #0d9488; font-weight: 700; font-size: .8rem;
                        letter-spacing: .16em; text-transform: uppercase; }
        </style>""",
        unsafe_allow_html=True,
    )


def _step_node(step: StepView) -> str:
    color = _GRAPH_COLORS[step.state]
    weight = "700" if step.state == StepState.RUNNING else "600"
    duration = format_duration(step.duration_seconds)
    details = STEP_STATE_LABELS[step.state] + (f" · {duration}" if duration else "")
    return (
        f'<div style="border:1px solid {color};border-left:4px solid {color};border-radius:6px;'
        f'padding:6px 10px;white-space:nowrap;font-size:0.85rem">'
        f'{step.icon} <span style="font-weight:{weight}">{html.escape(step.label)}</span><br>'
        f'<span style="color:{color};font-size:0.75rem">{html.escape(details)}</span></div>'
    )


def continuation_trackers(
    service: PipelineService, group: RunGroup,
) -> list[tuple[str, RunTracker]]:
    return [
        (f"Tentativa automática {index}", RunTracker.from_events(service.runs.get_events(summary.run_id)))
        for index, summary in enumerate(group.secondary, start=1)
    ]


def render_pipeline_graph(
    tracker: RunTracker, continuations: list[tuple[str, RunTracker]] | None = None,
) -> None:
    arrow = '<div style="color:#8c959f;align-self:center">→</div>'
    stage_order = list(StageName)
    intervention = stage_order.index(StageName.AGENT_INTERVENTION)

    def chain(current: RunTracker, index: int) -> str:
        steps = current.steps
        if index:
            steps = [
                step for step in steps
                if not (step.stage == StageName.AGENT_INTERVENTION and step.started_at is None)
                and not (step.stage == StageName.REVALIDATION and step.state == StepState.SKIPPED)
            ]
        if not continuations or index >= len(continuations):
            return arrow.join(_step_node(step) for step in steps)
        before = [step for step in steps if stage_order.index(step.stage) <= intervention]
        after = [step for step in steps if step not in before and step.state != StepState.SKIPPED]
        label, child = continuations[index]
        nested = (
            f'<div role="group" aria-label="{html.escape(label)}" style="max-width:100%;'
            f'border:1px dashed #0d9488;border-radius:8px;padding:8px">'
            f'<div style="font-size:.75rem;color:#0d9488;margin-bottom:6px">{html.escape(label)}</div>'
            f'<div style="display:flex;flex-wrap:wrap;gap:6px">{chain(child, index + 1)}</div></div>'
        )
        return arrow.join([
            *(_step_node(step) for step in before), nested, *(_step_node(step) for step in after),
        ])

    st.markdown(
        '<div style="display:flex;flex-wrap:wrap;gap:6px;margin:0.5rem 0 1rem 0">'
        + chain(tracker, 0) + "</div>",
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


def render_live(
    placeholder: Any, tracker: RunTracker, scenario_id: str, *, service: PipelineService | None = None,
) -> None:
    primary = tracker
    continuations: list[tuple[str, RunTracker]] = []
    if service is not None and tracker.events:
        run_id = tracker.events[0].run_id
        incident = service.incidents.get_for_run(run_id)
        if incident is not None:
            groups = group_runs(
                service.incidents.list_attempts(incident.incident_id),
                service.actions.list_actions(incident.incident_id),
            )
            group = next(group for group in groups if run_id in group.run_ids)
            if group.primary.run_id != run_id:
                primary = RunTracker.from_events(service.runs.get_events(group.primary.run_id))
            continuations = continuation_trackers(service, group)
    with placeholder.container():
        st.subheader(f"🟡 Em execução — {scenario_id}")
        current = tracker.current_step
        st.caption(f"Etapa atual: **{current.label}**" if current else "A concluir a execução…")
        render_pipeline_graph(primary, continuations)
        render_steps(primary)
        for label, child in continuations:
            with st.expander(f"Logs · {label}"):
                render_steps(child)


def _local_time(summary: RunSummary) -> str:
    return f"{summary.started_at.astimezone():%d/%m %H:%M:%S}"


def render_history(groups: list[RunGroup]) -> None:
    st.markdown("#### Execuções")
    if not groups:
        st.info("Ainda não há execuções. Escolhe um cenário e clica em **Executar pipeline**.")
        return
    statuses = [group.status for group in groups]
    st.caption("  ·  ".join(
        f"{label}: **{statuses.count(status)}**" for status, label in _HISTORY_BADGES.items()
    ))
    by_id = {group.primary.run_id: group for group in groups}
    roots = {run_id: group.primary.run_id for group in groups for run_id in group.run_ids}
    # A widget's value can only be changed before it is created in the rerun.
    if NEXT_SELECTION_KEY in st.session_state:
        requested = st.session_state.pop(NEXT_SELECTION_KEY)
        st.session_state[SELECTED_KEY] = roots.get(requested, requested)
    elif SELECTED_KEY in st.session_state:
        selected = st.session_state[SELECTED_KEY]
        st.session_state[SELECTED_KEY] = roots.get(selected, selected)
    if st.session_state.get(SELECTED_KEY) not in by_id:
        st.session_state.pop(SELECTED_KEY, None)
    st.radio(
        "Execução selecionada",
        options=list(by_id),
        key=SELECTED_KEY,
        label_visibility="collapsed",
        format_func=lambda run_id: (
            f"{_HISTORY_BADGES[by_id[run_id].status]} · "
            f"{by_id[run_id].primary.scenario_id} · {_local_time(by_id[run_id].primary)}"
            + (f" · +{len(by_id[run_id].secondary)} automática(s)" if by_id[run_id].secondary else "")
        ),
    )


def render_run(
    result: PipelineRun, summary: RunSummary, *,
    continuations: list[tuple[str, RunTracker]] | None = None,
    current: RunSummary | None = None,
) -> None:
    tracker = RunTracker.from_events(result.events)

    st.subheader(f"{_HISTORY_BADGES[current.status if current else summary.status]} — {result.scenario_id}")
    st.caption(
        f"Execução `{result.run_id}` · pipeline `{result.pipeline_id}` "
        f"(versão `{summary.pipeline_version}`) · iniciada {_local_time(summary)} · "
        f"qualidade {'inicial ' if continuations else ''}`{result.quality_status.value}`"
    )
    if continuations:
        st.caption(
            f"Estado atual inclui {len(continuations)} tentativa(s) automática(s). "
            "Os IDs técnicos mantêm-se na auditoria; o histórico usa a execução principal."
        )
        if current is not None:
            st.caption(f"Qualidade da tentativa atual: `{current.quality_status.value}`.")
        render_pipeline_graph(tracker, continuations)
        with st.expander("Métricas e resultado da execução principal"):
            render_result_details(result)
    else:
        render_result_details(result, graph=tracker)


def render_result_details(result: PipelineRun, *, graph: RunTracker | None = None) -> None:
    metrics = run_metrics(result)
    cards = [*st.columns(3), *st.columns(3)]
    cards[0].metric("Registos recebidos", metrics.records_received)
    cards[1].metric("Registos carregados", metrics.records_loaded)
    cards[2].metric("Duração", format_duration(metrics.duration_seconds) or "0 ms")
    cards[3].metric("Regras falhadas", metrics.rules_failed)
    cards[4].metric("Linhas afetadas", metrics.rows_affected)
    cards[5].metric("Atraso (min)", metrics.delay_minutes)

    if graph is not None:
        render_pipeline_graph(graph)
    if result.incident is not None:
        st.warning(f"Incidente detetado nesta tentativa: `{result.incident.kind}` — {result.incident.summary}")
    for error in result.errors:
        st.error(error)

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

def render_data(result: PipelineRun) -> None:
    selected = st.selectbox(
        "Vista dos dados", ["Recebidos", "Transformados", "Carregados"], key=f"data_view_{result.run_id}",
    )
    records = {
        "Recebidos": result.input_records, "Transformados": result.records, "Carregados": result.output_records,
    }[selected]
    if records:
        st.dataframe(records, hide_index=True, width="stretch")
    else:
        st.info("Não existem registos nesta vista.")
    st.download_button(
        "Descarregar execução (JSON)", result.model_dump_json(indent=2),
        file_name=f"run-{result.run_id}.json", mime="application/json",
        key=f"download_run_{result.run_id}",
    )
