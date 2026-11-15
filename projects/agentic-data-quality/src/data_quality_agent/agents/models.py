"""Validated reports exchanged by the orchestrator and specialists."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AgentRole = Literal["quality", "diagnosis", "remediation", "reviewer"]


class SpecialistReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: AgentRole
    summary: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    uncertainties: list[str] = Field(default_factory=list)
    recommendation: str = Field(min_length=1)
    recovery_confirmed: bool = False


class OrchestrationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["awaiting_correction", "unresolved", "resolved"]
    summary: str = Field(min_length=1)
    probable_cause: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    next_step: str = Field(min_length=1)
