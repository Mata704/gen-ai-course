"""Tool gateway: the single path for every tool call, local, action or through the MCP server.

The hooks that decide and filter (allowlist, budget, pinning, size, trust) are in harness/hooks.py.
Every call is written to the local `tool_calls` audit table, including blocked and failed ones,
with the source of the tool. An action denied by its policy (harness/policies.py) is a blocked call.
The external MCP server is never written to.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import ValidationError, validate_call

from data_quality_agent.harness.hooks import (
    MAX_CALLS_PER_SESSION,
    ToolSession,
    after_tool,
    before_tool,
)
from data_quality_agent.harness.policies import PolicyDenied
from data_quality_agent.persistence.audit import AuditRepository
from data_quality_agent.tools.actions import RemediationActions
from data_quality_agent.tools.catalog import AGENTS, CATALOG, ToolSpec
from data_quality_agent.tools.data_tools import DataQualityTools, ToolInputError
from data_quality_agent.tools.platform_client import PlatformClient, RemoteToolError


class ToolGateway:
    def __init__(
        self,
        tools: DataQualityTools,
        audit: AuditRepository,
        agent: str,
        *,
        platform: PlatformClient | None = None,
        actions: RemediationActions | None = None,
        run_id: str | None = None,
        max_calls: int = MAX_CALLS_PER_SESSION,
    ) -> None:
        if agent not in AGENTS:
            raise ValueError(f"Unknown agent '{agent}'. Expected one of: {', '.join(AGENTS)}.")
        self.tools = tools
        self.audit = audit
        self.platform = platform
        self.actions = actions
        self.session = ToolSession(agent=agent, run_id=run_id, max_calls=max_calls)

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        self.session.calls += 1
        spec = CATALOG.get(name)

        reason = before_tool(
            self.session, name, spec, arguments,
            platform=self.platform, actions_enabled=self.actions is not None,
        )
        if reason is not None or spec is None:
            self._record(name, spec, arguments, "blocked", reason or "", started)
            return {"status": "blocked", "reason": reason}

        try:
            result = await self._execute(spec, arguments)
        except PolicyDenied as denied:
            result = after_tool(spec, {"status": "blocked", "reason": f"Policy: {denied}"})
            self._record(name, spec, arguments, "blocked", result.get("reason", ""), started)
            return result
        except (ToolInputError, ValidationError, RemoteToolError) as error:
            detail = _validation_message(error) if isinstance(error, ValidationError) else str(error)
            result = after_tool(spec, {"error": detail})
            self._record(name, spec, arguments, "error", result.get("error", ""), started)
            return result
        except Exception as error:
            self._record(name, spec, arguments, "error", f"{type(error).__name__}: {error}", started)
            return {"error": f"Tool '{name}' failed with an internal error; report it instead of retrying."}

        result = after_tool(spec, result)
        outcome = "error" if "error" in result else "ok"
        call_id = self._record(name, spec, arguments, outcome, result.get("error", ""), started)
        return {**result, "tool_ref": f"tool:{call_id}"} if outcome == "ok" else result

    async def _execute(self, spec: ToolSpec, arguments: dict[str, Any]) -> dict[str, Any]:
        if spec.action:
            assert self.actions is not None  # checked by before_tool
            return await validate_call(getattr(self.actions, spec.name))(**arguments)
        if spec.source == "local":
            return validate_call(getattr(self.tools, spec.name))(**arguments)
        assert self.platform is not None  # checked by before_tool
        return await self.platform.call(spec.name, arguments)

    def _record(
        self, name: str, spec: ToolSpec | None, arguments: dict[str, Any], outcome: str, detail: str,
        started: float,
    ) -> int:
        run_id = arguments.get("run_id")
        return self.audit.record(
            agent=self.session.agent,
            tool=name,
            source=spec.source if spec else None,
            arguments=arguments,
            run_id=run_id if isinstance(run_id, str) else self.session.run_id,
            outcome=outcome,  # type: ignore[arg-type]
            detail=detail,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )


def _validation_message(error: ValidationError) -> str:
    problems = [f"{'.'.join(map(str, item['loc']))}: {item['msg']}" for item in error.errors()]
    return "Invalid arguments: " + "; ".join(problems)
