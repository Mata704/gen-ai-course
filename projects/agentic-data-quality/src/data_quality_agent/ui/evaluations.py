"""Launch evaluations, retain their history and inspect each case without polluting live runs."""

import sqlite3
from pathlib import Path

import streamlit as st

from data_quality_agent.evaluation import evaluate_cases, load_cases
from data_quality_agent.evaluation.storage import EvaluationRepository
from data_quality_agent.harness.model import configured_model
from data_quality_agent.service import PipelineService
from data_quality_agent.ui.observability import incident_run_ids, render_agents, render_logs, render_usage
from data_quality_agent.ui.view_model import format_duration


def render_evaluations(service: PipelineService) -> None:
    st.header("Avaliação")
    st.caption(
        "Casos versionados, resultados verificáveis e histórico persistido. "
        "As bases de cada caso ficam separadas das execuções operacionais."
    )
    repository = EvaluationRepository(service.database)
    cases = load_cases()
    with st.container(border=True):
        selected = st.multiselect(
            "Cenários a avaliar", [case.scenario_id for case in cases],
            default=[case.scenario_id for case in cases], key="evaluation_cases",
        )
        agents = st.checkbox("Avaliar também os agentes", key="evaluation_agents")
        st.caption(
            "Sem esta opção, não são feitas chamadas a modelos. Com agentes, usa a configuração OpenAI "
            "e verifica também decisões, papéis e ações; pode consumir tokens."
        )
        if st.button("Executar avaliação", type="primary", key="execute_evaluation"):
            if not selected:
                st.error("Seleciona pelo menos um cenário.")
            else:
                try:
                    model = configured_model() if agents else None
                    with st.spinner("A executar e verificar os casos selecionados…"):
                        report = evaluate_cases(
                            with_agents=agents, model=model, scenario_ids=selected,
                            workdir=service.database.path.resolve().parent / "evaluations",
                        )
                        evaluation_id = repository.save(report)
                    st.session_state["selected_evaluation"] = evaluation_id
                except (OSError, ValueError, sqlite3.Error) as error:
                    st.error(f"A avaliação não terminou: {error}")

    history = repository.list_reports()
    if not history:
        st.info("Ainda não existem avaliações guardadas. Começa pelos casos determinísticos, sem API.")
        return
    by_id = dict(history)
    if st.session_state.get("selected_evaluation") not in by_id:
        st.session_state.pop("selected_evaluation", None)
    evaluation_id = st.selectbox(
        "Histórico de avaliações", list(by_id), key="selected_evaluation",
        format_func=lambda value: (
            f"{by_id[value].started_at.astimezone():%d/%m %H:%M:%S} · "
            f"{by_id[value].mode} · {by_id[value].passed_cases}/{len(by_id[value].results)} aprovados · {value[:8]}"
        ),
    )
    report = by_id[evaluation_id]
    cards = st.columns(4)
    cards[0].metric("Casos aprovados", report.passed_cases)
    cards[1].metric("Casos reprovados", report.failed_cases)
    cards[2].metric("Taxa de aprovação", f"{report.passed_cases / len(report.results):.0%}" if report.results else "N/D")
    cards[3].metric("Duração da avaliação", format_duration((report.finished_at - report.started_at).total_seconds()))
    if report.failed_cases:
        st.warning("Há casos que não cumprem as expectativas. Consulta o detalhe e os logs.")
    else:
        st.success("Todos os casos selecionados passaram.")
    st.caption(
        f"Modo: {report.mode} · modelo: {report.model_name or 'sem modelo'} · "
        "Não é uma pontuação semântica do diagnóstico."
    )
    st.download_button(
        "Descarregar relatório de avaliação", report.model_dump_json(indent=2),
        file_name=f"evaluation-{evaluation_id}.json", mime="application/json", key="evaluation_download",
    )
    st.dataframe([
        {
            "Cenário": result.scenario_id, "Aprovado": result.passed,
            "Duração": format_duration(result.duration_ms / 1000) if result.duration_ms is not None else "N/D",
            "Verificações falhadas": sum(not check.passed for check in result.checks),
            "Pedidos ao modelo": len(result.model_calls), "Erro": result.error_type,
        }
        for result in report.results
    ], hide_index=True, width="stretch")
    with st.expander("Consumo de todos os casos"):
        render_usage(
            [call for result in report.results for call in result.model_calls],
            key=f"evaluation_{evaluation_id}",
        )
    case_id = st.selectbox(
        "Detalhe do caso", [result.scenario_id for result in report.results],
        key=f"evaluation_case_{evaluation_id}",
    )
    result = next(result for result in report.results if result.scenario_id == case_id)
    st.dataframe([
        {
            "Verificação": check.name, "Passou": check.passed,
            "Esperado": str(check.expected), "Observado": str(check.actual),
        }
        for check in result.checks
    ], hide_index=True, width="stretch")
    if result.error_type:
        st.error(f"A execução deste caso registou: {result.error_type}")
    if result.control_database is None or not Path(result.control_database).is_file():
        st.info("Os dados detalhados deste caso não estão disponíveis; o relatório e a telemetria mantêm-se guardados.")
        return
    case_service = PipelineService(result.control_database)
    if result.run_id is not None:
        ids = incident_run_ids(case_service, result.run_id)
        with st.expander("Logs e auditoria do caso", expanded=not result.passed):
            render_logs(case_service, ids, key=f"eval_{evaluation_id}_{case_id}")
        with st.expander("Agentes e tokens do caso"):
            render_agents(case_service, ids, key=f"eval_{evaluation_id}_{case_id}")
