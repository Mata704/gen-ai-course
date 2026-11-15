"""Incident history, agent reports and user-submitted batch corrections."""

import json

import streamlit as st

from data_quality_agent.harness.model import configured_model
from data_quality_agent.harness.team import AgentExecutionError
from data_quality_agent.corrections import MAX_BATCH_BYTES
from data_quality_agent.service import PipelineService
from data_quality_agent.simulator.events import EventListener
from data_quality_agent.simulator.models import PipelineEvent, PipelineRun, PipelineStatus
from data_quality_agent.ui.components import NEXT_SELECTION_KEY, render_live
from data_quality_agent.ui.view_model import RunTracker


def _progress(label: str, events: list[PipelineEvent] | None = None) -> EventListener:
    placeholder = st.empty()
    tracker = RunTracker.from_events(events) if events is not None else RunTracker()

    def on_event(event: PipelineEvent) -> None:
        tracker.apply(event)
        render_live(placeholder, tracker, label)

    return on_event


def _render_actions(service: PipelineService, incident_id: str) -> None:
    actions = service.actions.list_actions(incident_id)
    if not actions:
        return
    st.markdown("#### Ações automáticas")
    st.caption("Pedidas pelo agente de remediação e permitidas pela política da pipeline (verificada em código).")
    st.dataframe(
        [
            {"Ação": action.action, "Estado": action.status, "Sobre": action.source_run_id,
             "Nova tentativa": action.result_run_id or "", "Pedida por": action.requested_by,
             "Detalhe": action.detail}
            for action in actions
        ],
        hide_index=True, width="stretch",
    )
    held = service.actions.list_failed_records(incident_id)
    if held:
        with st.expander(f"Registos em quarentena ({len(held)}) — para revisão humana; não são enviados aos agentes"):
            st.dataframe(
                [
                    {"Estado": item.status, "Tentativa": item.source_run_id, "Posição": item.position,
                     "Regras falhadas": ", ".join(item.rule_ids), **item.record}
                    for item in held
                ],
                hide_index=True, width="stretch",
            )


def render_incident(service: PipelineService, result: PipelineRun, run_agents: bool) -> None:
    incident = service.incidents.get_for_run(result.run_id)
    if incident is None:
        return
    st.markdown("#### Incidente e tentativas")
    st.caption(f"Incidente `{incident.incident_id}` · estado `{incident.status}`")
    attempts = service.incidents.list_attempts(incident.incident_id)
    st.dataframe(
        [
            {"Execução": attempt.run_id, "Resultado": attempt.status,
             "Qualidade": attempt.quality_status.value, "Registos": attempt.record_count}
            for attempt in attempts
        ],
        hide_index=True, width="stretch",
    )
    _render_actions(service, incident.incident_id)
    latest = service.runs.get_run(incident.latest_run_id)
    if latest is None:
        st.info("A tentativa mais recente está em processamento.")
        return

    # An investigation started on one attempt may have created the next one through an action.
    for session in (s for attempt in attempts for s in service.incidents.list_sessions(attempt.run_id)):
        with st.expander(f"Investigação dos agentes ({session.run_id}) — {session.status}", expanded=True):
            if session.error:
                st.error(session.error)
            if session.outcome:
                st.markdown("**Conclusão do orquestrador**")
                st.json(session.outcome)
            for step in service.incidents.list_steps(session.session_id):
                with st.expander(f"{step.agent} · {step.kind} · {step.timestamp:%H:%M:%S}"):
                    st.code(step.message, language=None)

    busy = incident.status in ("investigating", "correcting")
    if incident.status == "resolved":
        st.success("Incidente resolvido: o lote passou nas regras e o carregamento foi verificado.")
        return

    if st.button("Investigar com agentes", disabled=busy, key=f"analyze_{incident.incident_id}"):
        try:
            service.analyze(
                latest.run_id, configured_model(),
                on_event=_progress("Investigação do incidente", latest.events),
            )
        except AgentExecutionError as error:
            st.session_state["execution_error"] = str(error)
        except (OSError, ValueError) as error:
            st.error(str(error))
            return
        current = service.incidents.get_for_run(latest.run_id)
        st.session_state[NEXT_SELECTION_KEY] = current.latest_run_id if current else latest.run_id
        st.rerun()

    if latest.pipeline_status == PipelineStatus.SUCCEEDED:
        st.info("O lote já foi carregado. Repete apenas a investigação/verificação, sem duplicar a entrega.")
        return
    if busy:
        st.info("Aguarda a operação em curso antes de submeter outra correção.")
        return

    st.markdown("#### Submeter correção para este incidente")
    st.caption(
        "Uma nova tentativa preserva o histórico e as regras originais. "
        "As falhas sintéticas do cenário não são novamente injetadas. Limite: 1 MB."
    )
    with st.form(f"correction_{incident.incident_id}_{latest.run_id}"):
        uploaded = st.file_uploader("Ficheiro JSON corrigido (opcional)", type=["json"])
        payload = st.text_area(
            "Lote corrigido (JSON)",
            value=json.dumps(latest.input_records, indent=2, ensure_ascii=False), height=240,
            key=f"corrected_batch_{latest.run_id}",
        )
        reason = st.text_input("Motivo da correção", key=f"correction_reason_{latest.run_id}")
        submitted = st.form_submit_button("Validar e reprocessar correção", type="primary")
    if not submitted:
        return
    try:
        if uploaded is not None:
            if uploaded.size > MAX_BATCH_BYTES:
                raise ValueError("O lote corrigido excede o limite de 1 MB.")
            payload = uploaded.getvalue().decode("utf-8-sig")
        corrected = service.correct(
            latest.run_id, payload, reason,
            agent_model=configured_model() if run_agents else None,
            on_event=_progress("Correção do incidente"),
        )
    except AgentExecutionError as error:
        st.session_state["execution_error"] = str(error)
        st.session_state[NEXT_SELECTION_KEY] = error.run_id
    except (OSError, ValueError) as error:
        st.error(f"A correção não terminou: {error}")
        return
    else:
        st.session_state[NEXT_SELECTION_KEY] = corrected.run_id
    st.rerun()
