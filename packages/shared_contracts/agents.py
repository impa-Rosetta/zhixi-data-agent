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
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class AnalysisEventResponse(BaseModel):
    sequence: int
    event_type: str
    payload: dict[str, object]
    created_at: datetime
