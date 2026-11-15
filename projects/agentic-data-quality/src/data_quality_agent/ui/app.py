"""Data Quality Studio. Start with `uv run --locked data-quality-ui`."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import streamlit as st

from data_quality_agent.corrections import MAX_BATCH_BYTES, parse_corrected_batch
from data_quality_agent.harness.model import configured_model
from data_quality_agent.harness.team import AgentExecutionError
from data_quality_agent.persistence.memory import MemoryRepository
from data_quality_agent.service import PipelineService
from data_quality_agent.simulator.engine import SCENARIOS_DIR, load_scenario
from data_quality_agent.simulator.models import PipelineEvent, Scenario
from data_quality_agent.ui.components import (
    NEXT_SELECTION_KEY, SELECTED_KEY, apply_theme, continuation_trackers, render_data,
    render_history, render_live, render_result_details, render_run,
)
from data_quality_agent.ui.evaluations import render_evaluations
from data_quality_agent.ui.incidents import render_incident
from data_quality_agent.ui.observability import (
    render_group_agents, render_group_logs, render_observability,
)
from data_quality_agent.ui.view_model import RunTracker, group_runs

DEFAULT_SCENARIO = "healthy-orders"


def load_scenarios() -> dict[str, tuple[Path, Scenario]]:
    scenarios = {}
    for path in sorted(SCENARIOS_DIR.glob("*.json")):
        scenario = load_scenario(path)
        scenarios[scenario.scenario_id] = (path, scenario)
    return dict(sorted(scenarios.items(), key=lambda item: item[0] != DEFAULT_SCENARIO))


def execute_run(
    scenario: Scenario, service: PipelineService, run_agents: bool, payload: str | None = None,
) -> None:
    placeholder = st.empty()
    tracker = RunTracker()

    def on_event(event: PipelineEvent) -> None:
        tracker.apply(event)
        render_live(placeholder, tracker, scenario.scenario_id, service=service)

    try:
        records = parse_corrected_batch(payload) if payload is not None else None
        result = service.run(
            scenario, input_records=records, on_event=on_event,
            agent_model=configured_model() if run_agents else None,
        )
    except AgentExecutionError as error:
        st.session_state["execution_error"] = str(error)
        st.session_state[NEXT_SELECTION_KEY] = error.run_id
        st.rerun()
        return
    except (OSError, ValueError) as error:
        st.error(f"A execução não terminou: {error}")
        return
    st.session_state[NEXT_SELECTION_KEY] = result.run_id
    st.rerun()


def _new_run(service: PipelineService, run_agents: bool, *, expanded: bool) -> None:
    with st.expander("Iniciar execução", expanded=expanded):
        mode = st.radio(
            "Origem dos dados", ["Cenário de exemplo", "Lote próprio"], horizontal=True, key="input_mode",
        )
        payload = None
        uploaded = None
        if mode == "Cenário de exemplo":
            scenarios = load_scenarios()
            scenario_id = st.selectbox("Cenário", options=list(scenarios), key="scenario")
            _, scenario = scenarios[scenario_id]
            st.caption(scenario.description)
            if scenario.faults:
                st.caption("Falhas simuladas: " + ", ".join(fault.kind.value for fault in scenario.faults))
        else:
            scenario = Scenario(
                scenario_id="user-orders", pipeline_id="orders_daily", seed=0,
                description="User-submitted batch, without injected faults.", faults=[],
            )
            st.info(
                "Pipeline orders_daily · sem falhas injetadas · limite de 1 MB. "
                "Usa apenas dados sintéticos; as correções posteriores ficam ligadas ao mesmo incidente."
            )
        with st.form("start_pipeline"):
            if mode == "Lote próprio":
                uploaded = st.file_uploader("Lote JSON", type=["json"], key="new_batch_upload")
                payload = st.text_area(
                    "Ou cola o lote JSON", value="[]", height=140, key="new_batch_json",
                    help="Lista de objetos com order_id, customer_id, amount e status. O ficheiro tem prioridade.",
                )
            submitted = st.form_submit_button("▶ Executar pipeline", type="primary", key="execute_pipeline")
        if submitted:
            if uploaded is not None:
                if uploaded.size > MAX_BATCH_BYTES:
                    st.error("O lote excede o limite de 1 MB.")
                    return
                try:
                    payload = uploaded.getvalue().decode("utf-8-sig")
                except UnicodeError:
                    st.error("O ficheiro deve estar codificado em UTF-8.")
                    return
            execute_run(scenario, service, run_agents, payload)


def _memory(service: PipelineService, pipeline_id: str) -> None:
    st.markdown("#### Memória da pipeline")
    st.caption(
        "Consulta de notas guardadas pelo diagnóstico com proveniência e validade. "
        "A UI não cria nem altera memória fora desse fluxo."
    )
    scope = st.selectbox("Notas", ["Ativas", "Todas (inclui expiradas)"], key=f"memory_scope_{pipeline_id}")
    memories = MemoryRepository(service.database).list_for_pipeline(pipeline_id, active_only=scope == "Ativas")
    if not memories:
        st.info("Não existem notas neste âmbito para esta pipeline.")
    else:
        st.dataframe([
            {
                "Nota": memory.content, "Origem": memory.source_ref, "Autor": memory.created_by,
                "Criada (UTC)": memory.created_at.isoformat(), "Válida até (UTC)": memory.valid_until.isoformat(),
            } for memory in memories
        ], hide_index=True, width="stretch")


def _executions(service: PipelineService, run_agents: bool) -> None:
    groups = group_runs(service.runs.list_runs(limit=None), service.actions.list_actions())
    _new_run(service, run_agents, expanded=not groups)
    history, detail = st.columns([1, 3], gap="large")
    with history:
        with st.container(border=True):
            render_history(groups)
    with detail:
        if not groups:
            st.info("Inicia uma execução para consultar os resultados.")
            return
        selected_id = st.session_state.get(SELECTED_KEY, groups[0].primary.run_id)
        group = next(group for group in groups if group.primary.run_id == selected_id)
        summary = group.primary
        if summary.status == "running":
            st.warning(
                "Esta execução ainda não tem resultado final: pode estar em curso ou ter sido interrompida. "
                "Atualizar consulta o estado persistido, sem repetir a execução."
            )
            render_live(
                st.empty(), RunTracker.from_events(service.runs.get_events(selected_id)), summary.scenario_id,
                service=service,
            )
            render_group_logs(service, group, key=selected_id)
            return
        result = service.runs.get_run(selected_id)
        if result is None:
            st.error("A execução selecionada não está disponível.")
            return
        render_run(
            result, summary, continuations=continuation_trackers(service, group), current=group.latest,
        )
        intervention, agents, logs, data, memory = st.tabs([
            "Intervenção", "Agentes e tokens", "Logs e auditoria", "Dados e regras", "Memória",
        ])
        with intervention:
            if service.incidents.get_for_run(selected_id) is None:
                st.success("Sem incidente. A qualidade passou e a entrega foi verificada.")
            else:
                render_incident(service, result, run_agents)
        with agents:
            st.caption(
                "Consumo por tentativa. As continuações da mesma investigação podem ter pedidos "
                "atribuídos a tentativas diferentes; os totais gerais estão em Observabilidade."
            )
            render_group_agents(service, group, key=selected_id)
        with logs:
            render_group_logs(service, group, key=selected_id)
        with data:
            render_data(result)
            pipeline = service.runs.get_pipeline(result.pipeline_id, summary.pipeline_version)
            with st.expander("Regras desta execução"):
                if pipeline is not None:
                    st.json(pipeline.model_dump(mode="json"))
                else:
                    st.error("A definição histórica desta execução não foi encontrada.")
            for index, secondary in enumerate(group.secondary, start=1):
                with st.expander(f"Dados e métricas · Tentativa automática {index}"):
                    st.caption(f"ID técnico: `{secondary.run_id}` · estado `{secondary.status}`")
                    child = service.runs.get_run(secondary.run_id)
                    if child is None:
                        st.warning("Esta tentativa ainda não tem resultado final; consulta os seus logs.")
                    else:
                        render_result_details(child)
                        render_data(child)
        with memory:
            _memory(service, result.pipeline_id)


def _clean_workspace() -> None:
    try:
        PipelineService().clean()
    except (OSError, ValueError, sqlite3.Error) as error:
        st.session_state["execution_error"] = (
            f"Não foi possível concluir a limpeza; alguns dados podem já ter sido apagados: {error}"
        )
        return
    st.session_state.clear()


def main() -> None:
    st.set_page_config(page_title="Data Quality Studio", page_icon="🧪", layout="wide")
    apply_theme()
    with st.sidebar:
        st.markdown('<div class="studio-label">Data Quality</div>', unsafe_allow_html=True)
        st.title("Studio")
        page = st.radio(
            "Área de trabalho", ["Execuções", "Avaliação", "Observabilidade"], key="workspace_page",
        )
        st.divider()
        run_agents = st.checkbox(
            "Investigar incidentes com agentes (OpenAI)", value=False, key="run_agents",
            help="Usa OPENAI_MODEL e OPENAI_API_KEY do ambiente; os lotes não são enviados aos agentes.",
        )
        st.caption("Tokens de entrada/saída e modelos utilizados. Sem custos monetários.")
        st.button("Atualizar", key="refresh_workspace", width="stretch")
        if st.button("Clean", key="clean_workspace", width="stretch"):
            st.session_state["confirm_clean"] = True
        if st.session_state.get("confirm_clean"):
            st.warning(
                "Limpeza irreversível: apaga os dados, logs, memória, aprovações e relatórios "
                "da base de controlo, o warehouse e os dados de todas as avaliações na mesma pasta. "
                "Confirma apenas quando não houver execuções em curso."
            )
            st.caption("Os cenários, lotes de exemplo e a origem MCP não são alterados.")
            st.button(
                "Confirmar limpeza", key="confirm_clean_workspace", on_click=_clean_workspace,
                type="primary", width="stretch",
            )
            if st.button("Cancelar", key="cancel_clean_workspace", width="stretch"):
                st.session_state.pop("confirm_clean", None)
                st.rerun()
    st.title("Data Quality Studio")
    st.caption("Executa, investiga e valida — dos dados à evidência, num único espaço.")
    if "execution_error" in st.session_state:
        st.error(st.session_state.pop("execution_error"))
    try:
        service = PipelineService()
    except (OSError, ValueError, sqlite3.Error) as error:
        st.error(f"Não foi possível abrir a base de controlo: {error}")
        return
    if page == "Avaliação":
        render_evaluations(service)
    elif page == "Observabilidade":
        render_observability(service)
    else:
        _executions(service, run_agents)


main()
