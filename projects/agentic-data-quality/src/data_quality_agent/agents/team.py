"""Bounded dynamic delegation; only specialists can access data tools."""

from __future__ import annotations

from collections.abc import Callable

from pydantic_ai import Agent, ModelRetry, RunContext, Tool
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage, UsageLimits

from data_quality_agent.agents.models import AgentRole, OrchestrationResult, SpecialistReport
from data_quality_agent.agents.prompts import COMMON, ORCHESTRATOR, SPECIALISTS
from data_quality_agent.agents.toolset import build_tools
from data_quality_agent.context import incident_brief
from data_quality_agent.persistence.audit import AuditRepository
from data_quality_agent.persistence.repository import RunRepository
from data_quality_agent.simulator.models import PipelineStatus, QualityStatus
from data_quality_agent.tools import DataQualityTools, PlatformClient, ToolGateway

ROLES: tuple[AgentRole, ...] = ("quality", "diagnosis", "remediation", "reviewer")
LIMITS = UsageLimits(request_limit=40, tool_calls_limit=80)
AgentListener = Callable[[str, str, str], None]


class AgentExecutionError(RuntimeError):
    def __init__(self, run_id: str, message: str) -> None:
        super().__init__(message)
        self.run_id = run_id


class AgentTeam:
    def __init__(
        self, model: Model | str, runs: RunRepository, platform: PlatformClient,
        run_id: str, on_step: AgentListener,
    ) -> None:
        self.model = model
        self.runs = runs
        self.platform = platform
        self.run_id = run_id
        self.on_step = on_step
        self.usage = RunUsage()
        self.delegations = 0
        self.reports: list[SpecialistReport] = []
        self.specialists = {role: self._build_specialist(role) for role in ROLES}

    def _recovery_verified(self) -> bool:
        result = self.runs.get_run(self.run_id)
        return bool(
            result is not None
            and result.pipeline_status == PipelineStatus.SUCCEEDED
            and result.quality_status == QualityStatus.PASS
            and not result.findings
            and result.output_records == result.records
        )

    def _build_specialist(self, role: AgentRole) -> Agent[None, SpecialistReport]:
        gateway = ToolGateway(
            DataQualityTools(self.runs), AuditRepository(self.runs.database), role,
            platform=self.platform, run_id=self.run_id,
        )
        observed: set[str] = set()
        used: set[str] = set()
        tools = build_tools(
            gateway, observed, used, lambda text: self.on_step(role, "tool", text),
        )
        agent = Agent(
            self.model, output_type=SpecialistReport, name=role,
            instructions=f"{SPECIALISTS[role]} {COMMON}", tools=tools, retries=2,
            model_settings={"timeout": 30},
        )

        @agent.output_validator
        def validate(ctx: RunContext[None], report: SpecialistReport) -> SpecialistReport:
            if report.role != role:
                raise ModelRetry(f"Your role is {role}.")
            if not set(report.evidence_refs).issubset(observed):
                raise ModelRetry("Cite only refs from successful tools you actually called.")
            if report.recovery_confirmed:
                if role != "reviewer" or not self._recovery_verified():
                    raise ModelRetry("Recovery is not confirmed by the deterministic state.")
                if not {"get_quality_findings", "get_delivery_status"}.issubset(used):
                    raise ModelRetry("Read the quality findings and delivery status before confirming recovery.")
            return report

        return agent

    async def ask(self, role: AgentRole, task: str) -> SpecialistReport:
        self.delegations += 1
        if self.delegations > 12:
            raise RuntimeError("O limite de 12 delegações foi atingido.")
        if len(task) > 4000:
            raise ModelRetry("Delegate a focused task of at most 4000 characters.")
        self.on_step(role, "started", task)
        result = await self.specialists[role].run(
            f"Current attempt run_id: {self.run_id}.\nTask: {task}",
            usage=self.usage, usage_limits=LIMITS,
        )
        self.reports.append(result.output)
        self.on_step(role, "completed", result.output.model_dump_json())
        return result.output

    async def run(self, incident_id: str) -> OrchestrationResult:
        summary = self.runs.get_summary(self.run_id)
        if summary is None:
            raise ValueError(f"Unknown run '{self.run_id}'.")

        def delegation(role: AgentRole) -> Tool[None]:
            async def ask(task: str) -> SpecialistReport:
                return await self.ask(role, task)

            return Tool(
                ask, name=f"ask_{role}", takes_ctx=False,
                description=f"Delegate a focused task to the {role} specialist. {SPECIALISTS[role]}",
            )

        orchestrator = Agent(
            self.model, output_type=OrchestrationResult, name="orchestrator",
            instructions=ORCHESTRATOR, tools=[delegation(role) for role in ROLES],
            retries=2, model_settings={"timeout": 30},
        )

        @orchestrator.output_validator
        def validate(ctx: RunContext[None], outcome: OrchestrationResult) -> OrchestrationResult:
            observed = {ref for report in self.reports for ref in report.evidence_refs}
            if not set(outcome.evidence_refs).issubset(observed):
                raise ModelRetry("Cite evidence actually received from specialists.")
            if outcome.status == "awaiting_correction" and not any(
                report.role == "remediation" for report in self.reports
            ):
                raise ModelRetry("Ask remediation for the correction requirements first.")
            if outcome.status == "resolved" and not (
                self._recovery_verified()
                and any(report.role == "reviewer" and report.recovery_confirmed for report in self.reports)
            ):
                raise ModelRetry("Resolution needs an independent review and verified quality/delivery.")
            return outcome

        prompt = (
            f"{incident_brief(self.runs, incident_id)}\n"
            f"Current attempt: {self.run_id}, status: {summary.status}, "
            f"quality: {summary.quality_status.value}. "
            "If this is a successful corrected attempt, ask the reviewer to check it. "
            "Otherwise investigate and recommend the next safe step."
        )
        self.on_step("orchestrator", "started", "A coordenar a investigação.")
        result = await orchestrator.run(prompt, usage=self.usage, usage_limits=LIMITS, timeout=120)
        self.on_step("orchestrator", "completed", result.output.model_dump_json())
        return result.output
