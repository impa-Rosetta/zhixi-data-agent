import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RunStatus = Literal[
    "queued",
    "running",
    "waiting_for_clarification",
    "waiting_for_confirmation",
    "completed",
    "failed_retryable",
    "failed",
    "cancelled",
]


class CreateAnalysisRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=2, max_length=10_000)
    max_model_calls: int = Field(default=6, ge=1, le=20)
    max_tool_calls: int = Field(default=12, ge=1, le=50)
    max_total_tokens: int = Field(default=32_000, ge=1000, le=500_000)
    max_runtime_seconds: int = Field(default=300, ge=10, le=3600)


class AppendAnalysisMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=10_000)


class ConfirmAnalysisRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved: bool


class AnalysisRunResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    status: RunStatus
    current_node: str
    context: dict[str, object]
    frozen_versions: dict[str, object]
    budget: dict[str, object]
    model_calls: int
    tool_calls: int
    total_tokens: int
    replan_count: int
    error_code: str | None
    version: int
    cancel_requested_at: datetime | None
    started_at: datetime | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class AnalysisEventResponse(BaseModel):
    sequence: int
    event_type: str
    payload: dict[str, object]
    created_at: datetime


class AnalysisRunSummaryResponse(BaseModel):
    id: uuid.UUID
    status: RunStatus
    current_node: str
    goal: str
    error_code: str | None
    model_calls: int
    tool_calls: int
    total_tokens: int
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class AnalysisRunPage(BaseModel):
    items: list[AnalysisRunSummaryResponse]
    total: int
    limit: int
    offset: int


class AnalysisMessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    context_patch: dict[str, object]
    created_at: datetime


class AnalysisPlanResponse(BaseModel):
    id: uuid.UUID
    revision: int
    goal: str
    document: dict[str, object]
    requires_confirmation: bool
    confirmed_at: datetime | None
    created_at: datetime


class AnalysisStepResponse(BaseModel):
    id: uuid.UUID
    plan_id: uuid.UUID
    step_key: str
    tool_name: str
    arguments: dict[str, object]
    dependencies: list[str]
    status: str
    error_code: str | None
    started_at: datetime | None
    finished_at: datetime | None


class AnalysisToolCallResponse(BaseModel):
    id: uuid.UUID
    step_id: uuid.UUID
    tool_name: str
    tool_version: str
    argument_digest: str
    status: str
    result_summary: dict[str, object]
    error_code: str | None
    created_at: datetime


class AnalysisArtifactResponse(BaseModel):
    id: uuid.UUID
    artifact_type: str
    summary: dict[str, object]
    content_digest: str
    created_at: datetime


class AnalysisEvidenceResponse(BaseModel):
    id: uuid.UUID
    artifact_id: uuid.UUID | None
    evidence_type: str
    reference: dict[str, object]
    evidence_digest: str
    created_at: datetime


class AnalysisValidationResponse(BaseModel):
    id: uuid.UUID
    validation_type: str
    outcome: str
    findings: list[dict[str, object]]
    created_at: datetime


class AnalysisRunViewResponse(BaseModel):
    run: AnalysisRunResponse
    messages: list[AnalysisMessageResponse]
    plan: AnalysisPlanResponse | None
    steps: list[AnalysisStepResponse]
    tool_calls: list[AnalysisToolCallResponse]
    artifacts: list[AnalysisArtifactResponse]
    evidence: list[AnalysisEvidenceResponse]
    validations: list[AnalysisValidationResponse]
    last_event_sequence: int
