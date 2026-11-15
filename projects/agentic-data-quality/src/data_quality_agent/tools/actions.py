"""The two automatic actions offered to the remediation agent.

Each one checks its policy (harness/policies.py) in code before anything runs; the agent only asks.
They create a new attempt of the same incident, which goes through every quality rule again, and
return its status and counts, never records.
"""

# No `from __future__ import annotations`: pydantic's validate_call reads these annotations at runtime.
from collections.abc import Callable
from typing import Any, Protocol

from data_quality_agent.tools.platform_client import PlatformClient, RemoteToolError


class ActionExecutor(Protocol):
    def source_system(self, run_id: str) -> str | None: ...

    def retry_ingestion(self, run_id: str, *, requested_by: str, source_status: str | None) -> dict[str, Any]: ...

    def quarantine_failed_records(self, run_id: str, *, requested_by: str) -> dict[str, Any]: ...


class RemediationActions:
    def __init__(
        self, executor: ActionExecutor, platform: PlatformClient | None, *,
        requested_by: str = "remediation", on_executed: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.executor = executor
        self.platform = platform
        self.requested_by = requested_by
        self.on_executed = on_executed

    async def retry_ingestion(self, run_id: str) -> dict[str, Any]:
        """Run the ingestion of a failed attempt again, as a new attempt of the same incident.
        Allowed only if the producing team reports the source as available on the Orders Platform and
        the pipeline's retry budget is not used up. Returns the new attempt and its status."""
        status = await self._source_status(run_id)
        return self._done(self.executor.retry_ingestion(run_id, requested_by=self.requested_by, source_status=status))

    async def quarantine_failed_records(self, run_id: str) -> dict[str, Any]:
        """Hold back only the records of a blocked attempt that failed row-level rules, and process the
        rest as a new attempt that goes through every quality rule again before delivery. Allowed only
        within the pipeline's quarantine limit and if no failed rule concerns the whole batch.
        Held-back records are kept for people to review. Returns the new attempt and the counts."""
        return self._done(self.executor.quarantine_failed_records(run_id, requested_by=self.requested_by))

    async def _source_status(self, run_id: str) -> str | None:
        system = self.executor.source_system(run_id)
        if system is None or self.platform is None or "get_source_status" not in self.platform.pinned:
            return None
        try:
            return (await self.platform.call("get_source_status", {"system_id": system})).get("status")
        except RemoteToolError:
            return None

    def _done(self, result: dict[str, Any]) -> dict[str, Any]:
        if self.on_executed is not None:
            self.on_executed(result)
        return result
