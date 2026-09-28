from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ReportArtifactType = Literal[
    "query_result",
    "analysis_summary",
    "chart_spec",
    "correlation_result",
    "anomaly_result",
    "visualization_data",
]
ReportSectionKind = Literal["data", "analysis", "chart"]


class StrictReportContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReportSourceRef(StrictReportContract):
    turn_id: uuid.UUID
    run_id: uuid.UUID
    artifact_id: uuid.UUID
    artifact_type: ReportArtifactType
    content_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    validation_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)


class ReportSection(StrictReportContract):
    kind: ReportSectionKind
    title: str = Field(min_length=1, max_length=200)
    summary: dict[str, object]
    source: ReportSourceRef


class ReportSpecV1(StrictReportContract):
    schema_version: Literal["1.0"] = "1.0"
    template_key: Literal["quality-analysis-v1"] = "quality-analysis-v1"
    template_version: Literal["1.0.0", "1.1.0"] = "1.0.0"
    workspace_id: uuid.UUID
    conversation_id: uuid.UUID
    created_by_user_id: uuid.UUID
    generated_at: datetime
    title: str = Field(min_length=1, max_length=300)
    sections: list[ReportSection] = Field(min_length=1, max_length=100)


ReportStatus = Literal["queued", "generating", "succeeded", "failed", "expired"]


class CreateAnalysisReportRequest(StrictReportContract):
    conversation_id: uuid.UUID
    turn_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    template_key: Literal["quality-analysis-v1"] = "quality-analysis-v1"

    @field_validator("turn_ids")
    @classmethod
    def _unique_turn_ids(cls, values: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(values) != len(set(values)):
            raise ValueError("turn_ids must be unique")
        return values


class AnalysisReportResponse(StrictReportContract):
    id: uuid.UUID
    workspace_id: uuid.UUID
    conversation_id: uuid.UUID
    created_by_user_id: uuid.UUID
    title: str
    status: ReportStatus
    template_key: str
    template_version: str
    renderer_version: str
    spec: ReportSpecV1
    source_digest: str
    content_digest: str | None
    error_code: str | None
    attempt_count: int
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AnalysisReportPage(StrictReportContract):
    items: list[AnalysisReportResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
