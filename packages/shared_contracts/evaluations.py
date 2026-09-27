from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suite_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$", max_length=32)
    track: Literal["offline"] = "offline"
    max_seconds: int = Field(default=300, ge=1, le=1800, strict=True)


class EvaluationRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workspace_id: UUID
    track: str
    status: str
    suite_version: str
    suite_digest: str
    dataset_id: str
    semantic_version: str
    model_version: str
    tool_version: str
    prompt_version: str
    budget: dict[str, object]
    summary: dict[str, object]
    calls_used: int
    tokens_used: int
    attempt_count: int
    error_code: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class EvaluationCaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    case_id: str
    category: str
    status: str
    attempt_count: int
    duration_ms: int
    assertion_results: list[dict[str, object]]
    run_references: list[str]
    error_code: str | None
