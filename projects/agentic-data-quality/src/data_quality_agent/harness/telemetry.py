"""Persist usage reported by each non-streaming model request, including validation retries."""

from collections.abc import Callable
from datetime import datetime, timezone
from time import perf_counter

from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings

from data_quality_agent.persistence.models import ModelCall
from data_quality_agent.persistence.telemetry import TelemetryRepository


class RecordedModel(WrapperModel):
    def __init__(
        self, model: Model | str, repository: TelemetryRepository, *,
        agent: str, run_id: Callable[[], str], session_id: str | None,
    ) -> None:
        super().__init__(model)
        self.repository = repository
        self.agent = agent
        self.run_id = run_id
        self.session_id = session_id

    async def request(
        self, messages: list[ModelMessage], model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        started_at = datetime.now(timezone.utc)
        started = perf_counter()
        run_id = self.run_id()
        response: ModelResponse | None = None
        try:
            response = await self.wrapped.request(messages, model_settings, model_request_parameters)
            return response
        finally:
            usage = response.usage if response is not None else None
            input_tokens: int | None = None
            output_tokens: int | None = None
            if usage is not None and usage.has_values() and not usage.unmeasured_requests:
                input_tokens, output_tokens = usage.input_tokens, usage.output_tokens
            self.repository.record(ModelCall(
                session_id=self.session_id, run_id=run_id, agent=self.agent,
                model_name=(response.model_name if response is not None else None) or self.model_name,
                provider=(response.provider_name if response is not None else None) or self.system,
                started_at=started_at, duration_ms=(perf_counter() - started) * 1000,
                outcome="ok" if response is not None else "error",
                input_tokens=input_tokens, output_tokens=output_tokens,
            ))
