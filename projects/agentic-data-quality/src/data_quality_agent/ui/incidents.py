"""Incident history, agent reports and user-submitted batch corrections."""

import json

import streamlit as st

from data_quality_agent.harness.model import configured_model
from data_quality_agent.harness.team import AgentExecutionError
from data_quality_agent.corrections import MAX_BATCH_BYTES
from data_quality_agent.harness.policies import PolicyDenied
from data_quality_agent.service import PipelineService
from data_quality_agent.simulator.events import EventListener
from data_quality_agent.simulator.models import PipelineEvent, PipelineRun, PipelineStatus, RuleKind
from data_quality_agent.ui.components import NEXT_SELECTION_KEY, render_live
from data_quality_agent.ui.view_model import RunTracker


def _progress(
    service: PipelineService, label: str, events: list[PipelineEvent] | None = None,
) -> EventListener:
    placeholder = st.empty()
    tracker = RunTracker.from_events(events) if events is not None else RunTracker()

    def on_event(event: PipelineEvent) -> None:
        tracker.apply(event)
        render_live(placeholder, tracker, label, service=service)

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
    if any(action.status == "running" for action in actions):
        if st.button("Retomar ações interrompidas", key=f"recover_actions_{incident_id}"):
            try:
                recovered = service.recover_interrupted_actions(incident_id)
            except (PolicyDenied, ValueError, OSError) as error:
                st.error(str(error))
            else:
                if recovered:
                    workflow = service.incidents.get_for_run(recovered[-1]["run_id"])
                    if workflow is not None:
                        st.session_state[NEXT_SELECTION_KEY] = workflow.latest_run_id
                st.rerun()
    held = service.actions.list_failed_records(incident_id)
    if held:
        with st.expander(f"Registos falhados ({len(held)}) — SQLite de controlo; não são enviados aos agentes"):
            st.dataframe(
                [
                    {"Estado": item.status, "Tentativa": item.source_run_id, "Posição": item.position,
                     "Regras falhadas": ", ".join(item.rule_ids), **item.record}
                    for item in held
                ],
                hide_index=True, width="stretch",
            )
            st.caption("Libertar/descartar altera apenas a classificação nesta tabela; não carrega dados no warehouse.")
            for item in (record for record in held if record.status == "held"):
                with st.form(f"request_failed_record_{incident_id}_{item.source_run_id}_{item.position}"):
                    target = st.selectbox(
                        f"Decisão para a posição {item.position}",
                        ("released", "discarded"),
                        format_func=lambda value: "Libertar para revisão" if value == "released" else "Descartar",
                    )
                    requester = st.text_input(
                        "Solicitante", key=f"requester_{incident_id}_{item.source_run_id}_{item.position}",
                    )
                    reason = st.text_input(
                        "Motivo", key=f"request_reason_{incident_id}_{item.source_run_id}_{item.position}",
                    )
                    attested = st.checkbox(
                        "Confirmo que estou autenticado",
                        help="A aplicação não verifica credenciais; esta caixa regista apenas a tua confirmação.",
                        key=f"request_attested_{incident_id}_{item.source_run_id}_{item.position}",
                    )
                    if st.form_submit_button("Pedir aprovação"):
                        try:
                            service.approvals.request(
                                source_run_id=item.source_run_id, position=item.position,
                                target_status=target, reason=reason, requested_by=requester,
                                identity_attested=attested,
                            )
                        except (PolicyDenied, ValueError) as error:
                            st.error(str(error))
                        else:
                            st.rerun()

    requests = service.approvals.list_for_incident(incident_id)
    if requests:
        st.dataframe(
            [
                {"Pedido": request.approval_id, "Posição": request.position,
                 "Destino": request.target_status, "Estado": request.status,
                 "Solicitante": request.requested_by, "Solicitante confirmou": request.requester_attested,
                 "Decisor": request.decided_by or "", "Decisor confirmou": request.decider_attested,
                 "Motivo": request.reason}
                for request in requests
            ],
            hide_index=True, width="stretch",
        )
    pending = [request for request in requests if request.status == "pending"]
    if pending:
        st.markdown("##### Pedidos de aprovação")
        for request in pending:
            st.write(
                f"Posição {request.position}: {request.target_status} — {request.reason} "
                f"(pedido por {request.requested_by})"
            )
            with st.form(f"decide_approval_{request.approval_id}"):
                decider = st.text_input("Aprovador", key=f"decider_{request.approval_id}")
                attested = st.checkbox(
                    "Confirmo que estou autenticado",
                    help="A aplicação não verifica credenciais; esta caixa regista apenas a tua confirmação.",
                    key=f"decider_attested_{request.approval_id}",
                )
                approve = st.form_submit_button("Aprovar e executar")
                reject = st.form_submit_button("Rejeitar")
                if approve or reject:
                    try:
                        if approve:
                            service.approvals.approve(
                                request.approval_id, decided_by=decider, identity_attested=attested,
                            )
                        else:
                            service.approvals.reject(
                                request.approval_id, decided_by=decider, identity_attested=attested,
                            )
                    except (PolicyDenied, ValueError) as error:
                        st.error(str(error))
                    else:
                        st.rerun()


def _render_rule_approvals(service: PipelineService, incident_id: str, pipeline_id: str) -> None:
    pipeline = service.current_pipeline(pipeline_id)
    options = [
        rule for rule in pipeline.rules
        if (rule.kind == RuleKind.MIN_ROWS and rule.minimum_count is not None)
        or (rule.kind == RuleKind.FRESHNESS and rule.maximum_delay_minutes is not None)
    ]
    if options:
        st.markdown("#### Pedir alteração de regra")
        st.caption("Com aprovação, o limite aplica-se a novas execuções; as tentativas antigas mantêm as regras originais.")
        rule_id = st.selectbox(
            "Regra", [rule.rule_id for rule in options], key=f"rule_choice_{incident_id}",
            format_func=lambda value: next(f"{rule.name} ({value})" for rule in options if rule.rule_id == value),
        )
        rule = next(rule for rule in options if rule.rule_id == rule_id)
        attribute = "minimum_count" if rule.kind == RuleKind.MIN_ROWS else "maximum_delay_minutes"
        current_value = int(getattr(rule, attribute))
        minimum, maximum = (1, 1000) if attribute == "minimum_count" else (0, 1440)
        with st.form(f"rule_change_request_{incident_id}"):
            proposed = st.number_input(
                "Novo limite", min_value=minimum, max_value=maximum, value=current_value, step=1,
                key=f"rule_value_{incident_id}_{rule_id}_{current_value}",
            )
            requester = st.text_input("Solicitante da alteração", key=f"rule_requester_{incident_id}")
            reason = st.text_input("Justificação", key=f"rule_reason_{incident_id}")
            attested = st.checkbox(
                "Confirmo que estou autenticado",
                help="A aplicação não verifica credenciais; esta caixa regista apenas a tua confirmação.",
                key=f"rule_request_attested_{incident_id}",
            )
            if st.form_submit_button("Pedir aprovação da alteração"):
                try:
                    service.rule_changes.request(
                        incident_id=incident_id, pipeline=pipeline, rule_id=rule.rule_id,
                        attribute=attribute, proposed_value=int(proposed), reason=reason,
                        requested_by=requester, identity_attested=attested,
                    )
                except (PolicyDenied, ValueError) as error:
                    st.error(str(error))
                else:
                    st.rerun()

    requests = service.rule_changes.list_for_incident(incident_id)
    if requests:
        st.dataframe(
            [
                {"Pedido": request.approval_id, "Regra": request.rule_id, "Atributo": request.attribute,
                 "Antes": request.previous_value, "Proposto": request.proposed_value, "Estado": request.status,
                 "Solicitante": request.requested_by, "Solicitante confirmou": request.requester_attested,
                 "Decisor": request.decided_by or "", "Decisor confirmou": request.decider_attested,
                 "Motivo": request.reason}
                for request in requests
            ],
            hide_index=True, width="stretch",
        )
    pending = [request for request in requests if request.status == "pending"]
    if pending:
        st.markdown("##### Pedidos de alteração pendentes")
        for request in pending:
            st.write(
                f"{request.rule_id}.{request.attribute}: {request.previous_value} → "
                f"{request.proposed_value} — {request.reason} (pedido por {request.requested_by})"
            )
            with st.form(f"decide_rule_change_{request.approval_id}"):
                decider = st.text_input("Aprovador", key=f"rule_decider_{request.approval_id}")
                attested = st.checkbox(
                    "Confirmo que estou autenticado",
                    help="A aplicação não verifica credenciais; esta caixa regista apenas a tua confirmação.",
                    key=f"rule_decider_attested_{request.approval_id}",
                )
                approve = st.form_submit_button("Aprovar alteração")
                reject = st.form_submit_button("Rejeitar alteração")
                if approve or reject:
                    try:
                        if approve:
                            service.rule_changes.approve(
                                request.approval_id, pipeline=service.current_pipeline(request.pipeline_id),
                                decided_by=decider, identity_attested=attested,
                            )
                        else:
                            service.rule_changes.reject(
                                request.approval_id, decided_by=decider, identity_attested=attested,
                            )
                    except (PolicyDenied, ValueError) as error:
                        st.error(str(error))
                    else:
                        st.rerun()


def render_incident(service: PipelineService, result: PipelineRun, run_agents: bool) -> None:
    incident = service.incidents.get_for_run(result.run_id)
    if incident is None:
        return
    st.markdown("#### Centro de intervenção")
    st.caption(f"Incidente `{incident.incident_id}` · estado `{incident.status}`")
    st.caption(
        "Corrige o lote, inicia uma investigação ou acompanha pedidos de aprovação. "
        "Solicitante e decisor devem ser diferentes; a confirmação por checkbox não autentica identidades."
    )
    attempts = service.incidents.list_attempts(incident.incident_id)
    with st.expander(f"Tentativas do incidente ({len(attempts)})"):
        st.dataframe(
            [
                {"Execução": attempt.run_id, "Resultado": attempt.status,
                 "Qualidade": attempt.quality_status.value, "Registos": attempt.record_count}
                for attempt in attempts
            ],
            hide_index=True, width="stretch",
        )
    with st.expander("Ações automáticas, quarentena e aprovações de linhas"):
        if not service.actions.list_actions(incident.incident_id):
            st.info("Ainda não existem ações. Só a remediação pode pedi-las, sujeita à política em código.")
        _render_actions(service, incident.incident_id)
    with st.expander("Alterações de regras e aprovações"):
        _render_rule_approvals(service, incident.incident_id, result.pipeline_id)
    latest = service.runs.get_run(incident.latest_run_id)
    if latest is None:
        st.info("A tentativa mais recente está em processamento.")
        return

    if incident.status == "investigating" and any(
        session.status == "running"
        for attempt in attempts
        for session in service.incidents.list_sessions(attempt.run_id)
    ):
        if st.button("Retomar investigação interrompida", key=f"recover_session_{incident.incident_id}"):
            try:
                service.recover_stale_investigation(incident.incident_id)
            except PolicyDenied as error:
                st.error(str(error))
            else:
                st.rerun()

    busy = incident.status in ("investigating", "correcting")
    if incident.status == "resolved":
        st.success("Incidente resolvido: o lote passou nas regras e o carregamento foi verificado.")
        return

    if st.button("Investigar com agentes", disabled=busy, key=f"analyze_{incident.incident_id}"):
        try:
            service.analyze(
                latest.run_id, configured_model(),
                on_event=_progress(service, "Investigação do incidente", latest.events),
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
            on_event=_progress(service, "Correção do incidente"),
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
