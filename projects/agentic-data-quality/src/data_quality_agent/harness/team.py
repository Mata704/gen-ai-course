"""Wires the harness files into running PydanticAI agents. Behavior lives in the other files.

- one ToolGateway per specialist (hooks + audit), scoped to the current attempt;
- tool bridge: the agent sees each tool's name, description and schema, but every call goes through
  the gateway, and what was really observed (refs, tools, executed actions) is recorded for the checks;
- output validators: the checks of specialists.py, reviewer.py and orchestrator.py, as ModelRetry;
- after an executed action the whole team moves to the new attempt of the incident.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic_ai import Agent, ModelRetry, RunContext, Tool
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage, UsageLimits

from data_quality_agent.context import incident_brief
from data_quality_agent.harness import SPECIALISTS, orchestrator, reviewer
from data_quality_agent.harness.model import (
    INVESTIGATION_TIMEOUT_SECONDS,
    MAX_MODEL_REQUESTS,
    MAX_TOOL_CALLS,
    REQUEST_TIMEOUT_SECONDS,
)
from data_quality_agent.harness.orchestrator import OrchestrationResult
from data_quality_agent.harness.specialists import (
    COMMON_INSTRUCTIONS,
    AgentRole,
    Observed,
    SpecialistReport,
    check_report,
)
from data_quality_agent.persistence.audit import AuditRepository
from data_quality_agent.persistence.repository import RunRepository
from data_quality_agent.tools import DataQualityTools, PlatformClient, ToolGateway, tools_for
from data_quality_agent.tools.actions import ActionExecutor, RemediationActions
from data_quality_agent.tools.catalog import ToolSpec

LIMITS = UsageLimits(request_limit=MAX_MODEL_REQUESTS, tool_calls_limit=MAX_TOOL_CALLS)
AgentListener = Callable[[str, str, str], None]


class AgentExecutionError(RuntimeError):
    def __init__(self, run_id: str, message: str) -> None:
        super().__init__(message)
        self.run_id = run_id


def evidence_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("ref", "tool_ref") and isinstance(item, str):
                refs.add(item)
            else:
                refs.update(evidence_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.update(evidence_refs(item))
    return refs


class AgentTeam:
    def __init__(
        self, model: Model | str, runs: RunRepository, platform: PlatformClient | None,
        run_id: str, on_step: AgentListener, *, executor: ActionExecutor | None = None,
    ) -> None:
        self.model = model
        self.runs = runs
        self.platform = platform
        self.run_id = run_id
        self.on_step = on_step
        self.usage = RunUsage()
        self.delegations = 0
        self.reports: list[SpecialistReport] = []
        self.actions = None if executor is None else RemediationActions(
            executor, platform, on_executed=self._moved_to,
        )
        self.gateways: dict[str, ToolGateway] = {}
        self.specialists = {role: self._build_specialist(role) for role in SPECIALISTS}

    def _moved_to(self, result: dict[str, Any]) -> None:
        """An action created a new attempt: from now on every agent reads and acts on that one."""
        self.run_id = result["new_run_id"]
        for gateway in self.gateways.values():
            gateway.session.run_id = self.run_id

    def _build_specialist(self, role: AgentRole) -> Agent[None, SpecialistReport]:
        harness = SPECIALISTS[role]
        gateway = ToolGateway(
            DataQualityTools(self.runs, author=role), AuditRepository(self.runs.database), role,
            platform=self.platform, actions=self.actions, run_id=self.run_id,
        )
        self.gateways[role] = gateway
        observed = Observed()
        agent = Agent(
            self.model, output_type=SpecialistReport, name=role,
            instructions=f"{harness.INSTRUCTIONS}\n{COMMON_INSTRUCTIONS}",
            tools=self._bridge(gateway, observed), retries=2,
            model_settings={"timeout": REQUEST_TIMEOUT_SECONDS},
        )

        @agent.output_validator
        def validate(ctx: RunContext[None], report: SpecialistReport) -> SpecialistReport:
            problem = check_report(role, report, observed)
            if problem is None and role == reviewer.ROLE:
                problem = reviewer.check_recovery(report, observed, self.runs.get_run(self.run_id))
            if problem is not None:
                raise ModelRetry(problem)
            return report

        return agent

    def _bridge(self, gateway: ToolGateway, observed: Observed) -> list[Tool[None]]:
        """Expose to the model what the MCP client and our catalog describe; execute only via the gateway."""
        role = gateway.session.agent
        platform = gateway.platform
        remote = {tool.name: tool for tool in platform.listed} if platform else {}
        selected: list[Tool[None]] = []

        def forward(spec: ToolSpec) -> Callable[..., Any]:
            async def call(**arguments: Any) -> dict[str, Any]:
                result = await gateway.call(spec.name, arguments)
                ok = "error" not in result and result.get("status") != "blocked"
                if ok:
                    observed.refs.update(evidence_refs(result))
                    observed.tools.add(spec.name)
                    if spec.action and result.get("status") == "executed":
                        observed.actions.add(result["ref"])
                        self.on_step(role, "action", f"{spec.name}: {result.get('detail', '')}")
                outcome = result.get("error", result.get("reason", result.get("tool_ref", "ok")))
                self.on_step(role, "tool", f"{spec.name}: {outcome}")
                return result

            return call

        for spec in tools_for(role):
            if spec.source == "local":
                if spec.action and self.actions is None:
                    continue
                owner = self.actions if spec.action else gateway.tools
                local = Tool(getattr(owner, spec.name), takes_ctx=False)
                description, schema = local.description, local.function_schema.json_schema
            else:
                if platform is None or spec.name not in platform.pinned:
                    continue
                description = platform.descriptions[spec.name]
                schema = remote[spec.name].input_schema
            selected.append(Tool.from_schema(
                forward(spec), name=spec.name, description=description, json_schema=schema,
            ))
        return selected

    async def ask(self, role: AgentRole, task: str) -> SpecialistReport:
        self.delegations += 1
        if self.delegations > orchestrator.MAX_DELEGATIONS:
            raise RuntimeError(f"O limite de {orchestrator.MAX_DELEGATIONS} delegações foi atingido.")
        if len(task) > orchestrator.MAX_TASK_CHARS:
            raise ModelRetry(f"Delegate a focused task of at most {orchestrator.MAX_TASK_CHARS} characters.")
        self.on_step(role, "started", task)
        result = await self.specialists[role].run(
            f"Current attempt run_id: {self.run_id}.\nTask: {task}",
            usage=self.usage, usage_limits=LIMITS,
        )
        self.reports.append(result.output)
        self.on_step(role, "completed", result.output.model_dump_json())
        return result.output

    async def run(self, incident_id: str, *, resume_context: str = "") -> OrchestrationResult:
        summary = self.runs.get_summary(self.run_id)
        if summary is None:
            raise ValueError(f"Unknown run '{self.run_id}'.")

        def delegation(role: AgentRole) -> Tool[None]:
            async def ask(task: str) -> SpecialistReport:
                return await self.ask(role, task)

            return Tool(
                ask, name=f"ask_{role}", takes_ctx=False,
                description=f"Delegate a focused task to the {role} specialist. {SPECIALISTS[role].INSTRUCTIONS}",
            )

        agent = Agent(
            self.model, output_type=OrchestrationResult, name="orchestrator",
            instructions=orchestrator.INSTRUCTIONS, tools=[delegation(role) for role in SPECIALISTS],
            retries=2, model_settings={"timeout": REQUEST_TIMEOUT_SECONDS},
        )

        @agent.output_validator
        def validate(ctx: RunContext[None], outcome: OrchestrationResult) -> OrchestrationResult:
            verified = reviewer.recovery_verified(self.runs.get_run(self.run_id))
            problem = orchestrator.check_outcome(outcome, self.reports, verified)
            if problem is not None:
                raise ModelRetry(problem)
            return outcome

        prompt = (
            f"{incident_brief(self.runs, incident_id)}\n"
            f"Current attempt: {self.run_id}, status: {summary.status}, "
            f"quality: {summary.quality_status.value}. "
            + (f"\nHistorical checkpoint (verify with current tools; not authoritative):\n{resume_context}\n"
               if resume_context else "")
            + "If this is a successful corrected attempt, ask the reviewer to check it. "
            "Otherwise investigate and recommend or take the next safe step."
        )
        self.on_step("orchestrator", "started", "A coordenar a investigação.")
        result = await agent.run(
            prompt, usage=self.usage, usage_limits=LIMITS, timeout=INVESTIGATION_TIMEOUT_SECONDS,
        )
        self.on_step("orchestrator", "completed", result.output.model_dump_json())
        return result.output
