from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ReportArtifactType = Literal["query_result", "analysis_summary", "chart_spec"]
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
    template_version: Literal["1.0.0"] = "1.0.0"
    workspace_id: uuid.UUID
    conversation_id: uuid.UUID
    created_by_user_id: uuid.UUID
    generated_at: datetime
    title: str = Field(min_length=1, max_length=300)
    sections: list[ReportSection] = Field(min_length=1, max_length=100)
