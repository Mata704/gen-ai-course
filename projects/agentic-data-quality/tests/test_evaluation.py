import json
from pathlib import Path

import pytest

from data_quality_agent.evaluation import evaluate_cases, load_cases
from data_quality_agent.evaluation.cli import main
from data_quality_agent.evaluation.storage import EvaluationRepository
from data_quality_agent.persistence.database import Database


def test_deterministic_evaluation_checks_all_versioned_scenarios(tmp_path: Path) -> None:
    report = evaluate_cases(workdir=tmp_path)

    assert report.mode == "deterministic"
    assert report.passed_cases == 6
    assert report.failed_cases == 0
    assert {result.scenario_id for result in report.results} == {
        case.scenario_id for case in load_cases()
    }


def test_evaluation_rejects_unknown_scenarios_and_missing_agent_model() -> None:
    with pytest.raises(ValueError, match="Unknown evaluation scenario"):
        evaluate_cases(scenario_ids=["not-a-scenario"])
    with pytest.raises(ValueError, match="agent model is required"):
        evaluate_cases(with_agents=True)


def test_cli_emits_a_machine_readable_report(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["--scenario", "healthy-orders"])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "deterministic"


def test_evaluation_report_history_and_case_logs_survive_a_new_session(tmp_path: Path) -> None:
    report = evaluate_cases(scenario_ids=["healthy-orders"], workdir=tmp_path / "cases")
    database = Database(tmp_path / "history.sqlite3")
    evaluation_id = EvaluationRepository(database).save(report)
    [stored] = EvaluationRepository(Database(database.path)).list_reports()

    assert stored[0] == evaluation_id
    assert stored[1] == report
    assert Path(stored[1].results[0].control_database).is_file()
