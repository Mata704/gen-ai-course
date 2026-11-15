from pathlib import Path

import pytest

from data_quality_agent.harness.policies import PolicyDenied
from data_quality_agent.persistence.audit import AuditRepository
from data_quality_agent.persistence.memory import MemoryRepository
from data_quality_agent.service import PipelineService
from data_quality_agent.simulator.engine import SCENARIOS_DIR
from data_quality_agent.tools.data_tools import DataQualityTools


def test_memory_requires_successful_same_incident_evidence_and_expires(tmp_path: Path) -> None:
    service = PipelineService(tmp_path / "history.sqlite3")
    run = service.run(SCENARIOS_DIR / "quality_issues.json")
    call_id = AuditRepository(service.database).record(
        agent="diagnosis", tool="get_run_summary", source="local", arguments={},
        run_id=run.run_id, outcome="ok", detail="", duration_ms=1,
    )
    memory = MemoryRepository(service.database)

    saved = memory.add(
        run_id=run.run_id, content="Orders source has had repeated status normalization failures.",
        source_ref=f"tool:{call_id}", created_by="diagnosis", valid_days=30,
    )
    assert memory.active_for_pipeline(run.pipeline_id) == [saved]
    assert DataQualityTools(service.runs).get_relevant_memory(run.run_id)["memories"] == [
        {
            "ref": f"memory:{saved.memory_id}",
            "content": saved.content,
            "source_ref": saved.source_ref,
            "created_at": saved.created_at.isoformat(),
            "valid_until": saved.valid_until.isoformat(),
        }
    ]
    with pytest.raises(PolicyDenied, match="successful tool result"):
        memory.add(
            run_id=run.run_id, content="Unsupported claim.", source_ref="tool:99999",
            created_by="diagnosis", valid_days=30,
        )
    with pytest.raises(PolicyDenied, match="personal data"):
        memory.add(
            run_id=run.run_id, content="Contact user@example.com for confirmation.",
            source_ref=f"tool:{call_id}", created_by="diagnosis", valid_days=30,
        )
    with service.database.transaction() as connection:
        connection.execute(
            "UPDATE incident_memories SET valid_until = '2000-01-01T00:00:00+00:00' "
            "WHERE memory_id = ?", (saved.memory_id,),
        )
    assert memory.active_for_pipeline(run.pipeline_id) == []
