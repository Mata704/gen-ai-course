"""Model usage, session reports and a filterable, exportable timeline."""

import json
from math import ceil
from typing import Literal

import streamlit as st

from data_quality_agent.persistence.audit import AuditRepository
from data_quality_agent.persistence.models import ModelCall
from data_quality_agent.persistence.telemetry import TelemetryRepository
from data_quality_agent.service import PipelineService
from data_quality_agent.ui.view_model import RunGroup, format_duration, group_runs


def _tokens(calls: list[ModelCall], field: Literal["input_tokens", "output_tokens"]) -> str:
    known = [value for call in calls if (value := getattr(call, field)) is not None]
    if not known:
        return "N/D"
    total = f"{sum(known):,}".replace(",", " ")
    return total if len(known) == len(calls) else f"≥ {total}"


def _percentile(values: list[float], percentile: float) -> float | None:
    return sorted(values)[max(0, ceil(len(values) * percentile) - 1)] if values else None


def render_usage(calls: list[ModelCall], *, key: str) -> None:
    st.markdown("#### Consumo de modelos")
    st.caption(
        "Tokens reportados pelo modelo; sem preços ou custos monetários. "
        "N/D = sem medição. Totais com ≥ estão incompletos. "
        "Só inclui pedidos registados desde a ativação da telemetria. "
        "Latência por pedido inclui a resposta completa, não o tempo até ao primeiro token."
    )
    cards = st.columns(4)
    cards[0].metric("Tokens de entrada", _tokens(calls, "input_tokens"))
    cards[1].metric("Tokens de saída", _tokens(calls, "output_tokens"))
    cards[2].metric("Pedidos ao modelo", len(calls))
    cards[3].metric("Pedidos com erro", sum(call.outcome == "error" for call in calls))
    if not calls:
        st.info("Sem telemetria de modelos neste âmbito. Execuções antigas não têm tokens recuperáveis.")
        return
    latencies = [call.duration_ms / 1000 for call in calls]
    left, right = st.columns(2)
    left.metric("Latência p50", format_duration(_percentile(latencies, .5)))
    right.metric("Latência p95", format_duration(_percentile(latencies, .95)))
    by_model = []
    for model in sorted({call.model_name for call in calls}):
        selected = [call for call in calls if call.model_name == model]
        by_model.append({
            "Modelo": model, "Pedidos": len(selected),
            "Tokens entrada": _tokens(selected, "input_tokens"),
            "Tokens saída": _tokens(selected, "output_tokens"),
            "Erros": sum(call.outcome == "error" for call in selected),
        })
    st.dataframe(by_model, hide_index=True, width="stretch")
    with st.expander("Detalhe de cada pedido ao modelo"):
        st.dataframe([
            {
                "Data (UTC)": call.started_at.isoformat(), "Agente": call.agent,
                "Modelo": call.model_name, "Fornecedor": call.provider, "Estado": call.outcome,
                "Tokens entrada": call.input_tokens, "Tokens saída": call.output_tokens,
                "Latência (ms)": round(call.duration_ms, 2), "Execução": call.run_id,
                "Investigação": call.session_id,
            }
            for call in calls
        ], hide_index=True, width="stretch")
        st.download_button(
            "Exportar telemetria", json.dumps([call.model_dump(mode="json") for call in calls], indent=2),
            file_name="model-calls.json", mime="application/json", key=f"usage_download_{key}",
        )


def incident_run_ids(service: PipelineService, run_id: str) -> list[str]:
    incident = service.incidents.get_for_run(run_id)
    if incident is None:
        return [run_id]
    return [attempt.run_id for attempt in service.incidents.list_attempts(incident.incident_id)]


def render_agents(service: PipelineService, run_ids: list[str], *, key: str) -> None:
    calls = TelemetryRepository(service.database).list_calls(run_ids=run_ids)
    render_usage(calls, key=key)
    sessions = [
        session for run_id in run_ids for session in service.incidents.list_sessions(run_id)
    ]
    if not sessions:
        st.info(
            "Não há investigação iniciada nesta tentativa. Uma continuação pode pertencer "
            "à investigação iniciada na execução principal."
        )
        return
    measured = {call.session_id for call in calls}
    if any(session.session_id not in measured for session in sessions):
        st.caption("Há investigações sem medição: anteriores à telemetria ou interrompidas antes do primeiro pedido.")
    for session in reversed(sessions):
        duration = (
            format_duration((session.finished_at - session.started_at).total_seconds())
            if session.finished_at is not None else "em curso"
        )
        with st.expander(f"Investigação · {session.status} · {duration} · {session.run_id[:8]}"):
            st.caption(f"Investigação `{session.session_id}` · execução `{session.run_id}`")
            if session.error:
                st.error(session.error)
            if session.outcome:
                st.markdown("**Conclusão do orquestrador**")
                st.write(session.outcome["summary"])
                st.json(session.outcome, expanded=False)
            for step in service.incidents.list_steps(session.session_id):
                with st.expander(f"{step.agent} · {step.kind} · {step.timestamp:%H:%M:%S}"):
                    st.code(step.message, language=None)


def render_logs(service: PipelineService, run_ids: list[str], *, key: str) -> None:
    rows = []
    for run_id in run_ids:
        for event in service.runs.get_events(run_id):
            rows.append({
                "Data (UTC)": event.timestamp.isoformat(), "Origem": "Pipeline",
                "Nível": event.level.value.upper(), "Ator": event.stage.value if event.stage else "pipeline",
                "Mensagem": event.message, "Execução": run_id, "Detalhe": event.kind.value,
                "Só simulação": event.simulation_only,
            })
        for session in service.incidents.list_sessions(run_id):
            for step in service.incidents.list_steps(session.session_id):
                rows.append({
                    "Data (UTC)": step.timestamp.isoformat(), "Origem": "Agentes",
                    "Nível": "ERROR" if step.kind == "error" else "INFO", "Ator": step.agent,
                    "Mensagem": step.message, "Execução": run_id, "Detalhe": step.kind,
                    "Só simulação": False,
                })
    tools = AuditRepository(service.database).list_calls(run_ids=run_ids, limit=None)
    for call in tools:
        rows.append({
            "Data (UTC)": call.called_at.isoformat(), "Origem": "Tools",
            "Nível": "INFO" if call.outcome == "ok" else "WARNING" if call.outcome == "blocked" else "ERROR",
            "Ator": call.agent, "Mensagem": f"{call.tool} · {call.outcome} · {call.detail}",
            "Execução": call.run_id,
            "Só simulação": False,
            "Detalhe": json.dumps({
                "tool_ref": f"tool:{call.call_id}", "source": call.source, "arguments": call.arguments,
                "duration_ms": call.duration_ms,
            }, ensure_ascii=False),
        })
    st.markdown("#### Timeline e auditoria")
    sources, levels, search = st.columns([1, 1, 2])
    source = sources.selectbox("Origem", ["Todas", "Pipeline", "Agentes", "Tools"], key=f"log_source_{key}")
    level = levels.selectbox("Nível", ["Todos", "INFO", "WARNING", "ERROR", "DEBUG"], key=f"log_level_{key}")
    query = search.text_input("Pesquisar nos logs", key=f"log_query_{key}").casefold()
    filtered = sorted((
        row for row in rows
        if (source == "Todas" or row["Origem"] == source)
        and (level == "Todos" or row["Nível"] == level)
        and (not query or query in json.dumps(row, ensure_ascii=False).casefold())
    ), key=lambda row: row["Data (UTC)"])
    st.caption(f"{len(filtered)} de {len(rows)} eventos · sem truncagem do histórico selecionado")
    if filtered:
        st.dataframe(filtered, hide_index=True, width="stretch")
        with st.expander("Inspecionar evento completo"):
            index = st.selectbox(
                "Evento", range(len(filtered)), key=f"log_detail_{key}",
                format_func=lambda value: (
                    f"{filtered[value]['Data (UTC)']} · {filtered[value]['Ator']} · "
                    f"{filtered[value]['Mensagem'][:70]}"
                ),
            )
            st.code(filtered[index]["Mensagem"], language=None)
            st.json(filtered[index], expanded=False)
        st.download_button(
            "Descarregar logs filtrados", json.dumps(filtered, indent=2, ensure_ascii=False),
            file_name="logs.json", mime="application/json", key=f"logs_download_{key}",
        )
    else:
        st.info("Nenhum evento corresponde aos filtros.")
    if tools:
        latency = _percentile([call.duration_ms / 1000 for call in tools], .95)
        left, middle, right = st.columns(3)
        left.metric("Chamadas a tools", len(tools))
        middle.metric("Tools bloqueadas", sum(call.outcome == "blocked" for call in tools))
        right.metric("Latência tools p95", format_duration(latency))


def render_group_agents(service: PipelineService, group: RunGroup, *, key: str) -> None:
    render_agents(service, [group.primary.run_id], key=key)
    for index, summary in enumerate(group.secondary, start=1):
        with st.expander(f"Agentes e tokens · Tentativa automática {index}"):
            st.caption(f"ID técnico: `{summary.run_id}`")
            render_agents(service, [summary.run_id], key=f"{key}_attempt_{summary.run_id}")


def render_group_logs(service: PipelineService, group: RunGroup, *, key: str) -> None:
    if group.secondary:
        st.caption(
            "Logs da execução principal. As tentativas automáticas estão nas secções abaixo; "
            "os passos da investigação partilhada mantêm a execução onde foram registados."
        )
    render_logs(service, [group.primary.run_id], key=key)
    for index, summary in enumerate(group.secondary, start=1):
        with st.expander(f"Logs e auditoria · Tentativa automática {index}"):
            st.caption(f"ID técnico: `{summary.run_id}`")
            render_logs(service, [summary.run_id], key=f"{key}_attempt_{summary.run_id}")


def render_observability(service: PipelineService) -> None:
    st.header("Observabilidade")
    st.caption("Telemetria das execuções desta base de controlo. As avaliações têm métricas e logs na sua própria área.")
    calls = TelemetryRepository(service.database).list_calls()
    models = sorted({call.model_name for call in calls})
    selected = st.multiselect("Modelos", models, default=models, key="metrics_models")
    render_usage([call for call in calls if call.model_name in selected], key="global")
    groups = group_runs(service.runs.list_runs(limit=None), service.actions.list_actions())
    if groups:
        by_id = {group.primary.run_id: group for group in groups}
        roots = {run_id: group.primary.run_id for group in groups for run_id in group.run_ids}
        if "global_log_runs" in st.session_state:
            st.session_state["global_log_runs"] = list(dict.fromkeys(
                roots[run_id] for run_id in st.session_state["global_log_runs"] if run_id in roots
            ))
        selected_runs = st.multiselect(
            "Execuções para consultar logs", options=list(by_id),
            format_func=lambda value: (
                f"{by_id[value].primary.scenario_id} · {by_id[value].status} · {value[:8]}"
            ),
            key="global_log_runs",
        )
        for run_id in selected_runs:
            with st.expander(f"Logs da execução principal · {run_id[:8]}", expanded=True):
                render_group_logs(service, by_id[run_id], key=f"global_{run_id}")
