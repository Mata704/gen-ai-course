import asyncio
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from data_quality_agent.harness.telemetry import RecordedModel
from data_quality_agent.persistence.telemetry import TelemetryRepository
from data_quality_agent.service import PipelineService
from data_quality_agent.simulator.engine import SCENARIOS_DIR


def test_model_usage_and_latency_are_persisted_without_prompt_content(tmp_path: Path) -> None:
    service = PipelineService(tmp_path / "history.sqlite3")
    run = service.run(SCENARIOS_DIR / "healthy.json")
    repository = TelemetryRepository(service.database)

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[TextPart("private response")], model_name="actual-model", provider_name="test-provider",
            usage=RequestUsage(input_tokens=123, output_tokens=17),
        )

    model = RecordedModel(
        FunctionModel(respond, model_name="actual-model"), repository,
        agent="quality", run_id=lambda: run.run_id, session_id=None,
    )
    asyncio.run(model.request(
        [ModelRequest(parts=[UserPromptPart("private prompt")])], None, ModelRequestParameters(),
    ))

    [call] = TelemetryRepository(service.database).list_calls(run_ids=[run.run_id])
    assert (call.input_tokens, call.output_tokens, call.model_name, call.provider) == (
        123, 17, "actual-model", "test-provider",
    )
    assert call.outcome == "ok" and call.duration_ms >= 0
    assert "private" not in call.model_dump_json()


def test_failed_model_request_is_not_reported_as_zero_usage(tmp_path: Path) -> None:
    service = PipelineService(tmp_path / "history.sqlite3")
    run = service.run(SCENARIOS_DIR / "healthy.json")
    repository = TelemetryRepository(service.database)

    def unavailable(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise TimeoutError("Model did not respond.")

    model = RecordedModel(
        FunctionModel(unavailable), repository, agent="diagnosis", run_id=lambda: run.run_id, session_id=None,
    )
    with pytest.raises(TimeoutError):
        asyncio.run(model.request(
            [ModelRequest(parts=[UserPromptPart("request")])], None, ModelRequestParameters(),
        ))

    [call] = repository.list_calls()
    assert call.outcome == "error"
    assert call.input_tokens is None and call.output_tokens is None
    assert call.duration_ms >= 0
