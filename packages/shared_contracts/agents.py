import json
import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
ConversationStatus = Literal["active", "archived"]
TurnRelation = Literal["initial", "continue", "refine", "explain", "compare", "switch_topic"]
TurnStatus = Literal["queued", "running", "waiting_for_user", "completed", "failed", "cancelled"]
TimeGrain = Literal["day", "week", "month", "quarter", "year"]
ComparisonMode = Literal["previous_period", "previous_year", "baseline"]
SortDirection = Literal["asc", "desc"]
ResultShape = Literal["scalar", "table", "time_series", "ranking", "comparison", "catalog"]
FilterOperator = Literal["eq", "neq", "gt", "gte", "lt", "lte", "in", "between"]


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalysisMetricContext(StrictContract):
    key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=200)


class AnalysisDimensionContext(StrictContract):
    key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=200)


class AnalysisTimeRangeContext(StrictContract):
    start: date | None = None
    end: date | None = None

    @model_validator(mode="after")
    def validate_order(self) -> "AnalysisTimeRangeContext":
        if self.start is None and self.end is None:
            raise ValueError("time range requires a start or end")
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("time range start must not be after end")
        return self


BoundedFilterString = Annotated[str, Field(max_length=500)]
FilterScalar = BoundedFilterString | int | float | bool


class AnalysisFilterContext(StrictContract):
    field_key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    operator: FilterOperator
    value: FilterScalar | None = None
    values: list[FilterScalar] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_value_shape(self) -> "AnalysisFilterContext":
        if (self.value is None) == (not self.values):
            raise ValueError("provide exactly one of value or values")
        if self.operator in {"in", "between"} and not self.values:
            raise ValueError("collection operator requires values")
        if self.operator not in {"in", "between"} and self.value is None:
            raise ValueError("scalar operator requires value")
        return self


class AnalysisSortContext(StrictContract):
    field_key: str | None = Field(default=None, min_length=1, max_length=100)
    direction: SortDirection
    limit: int | None = Field(default=None, ge=1, le=1000)


class AnalysisSemanticVersionContext(StrictContract):
    model_id: uuid.UUID
    version: int = Field(ge=1)


class AnalysisResultContext(StrictContract):
    artifact_id: uuid.UUID
    evidence_id: uuid.UUID | None = None
    shape: ResultShape
    row_count: int = Field(ge=0, le=1_000_000)
    primary_value: str | None = Field(default=None, max_length=200)
    unit: str | None = Field(default=None, max_length=50)


class AnalysisConversationContext(StrictContract):
    version: Literal[1] = 1
    topic_summary: str | None = Field(default=None, max_length=500)
    metric: AnalysisMetricContext | None = None
    dimensions: list[AnalysisDimensionContext] = Field(default_factory=list, max_length=10)
    time_range: AnalysisTimeRangeContext | None = None
    time_grain: TimeGrain | None = None
    filters: list[AnalysisFilterContext] = Field(default_factory=list, max_length=20)
    comparison: ComparisonMode | None = None
    sort: AnalysisSortContext | None = None
    semantic_version: AnalysisSemanticVersionContext | None = None
    last_result: AnalysisResultContext | None = None
    last_relation: TurnRelation | None = None

    @model_validator(mode="after")
    def validate_total_size(self) -> "AnalysisConversationContext":
        payload = self.model_dump(mode="json", exclude_none=True)
        if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 16_384:
            raise ValueError("conversation context exceeds 16 KiB")
        return self


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


class CreateAnalysisConversationRequest(CreateAnalysisRunRequest):
    """Create a conversation and its first immutable analysis run."""


class SendAnalysisConversationMessageRequest(AppendAnalysisMessageRequest):
    """Send a follow-up or clarification reply in an active conversation."""


class AnalysisConversationResponse(StrictContract):
    id: uuid.UUID
    workspace_id: uuid.UUID
    title: str = Field(min_length=1, max_length=300)
    status: ConversationStatus
    context: AnalysisConversationContext
    active_turn_id: uuid.UUID | None
    last_turn_sequence: int = Field(ge=0)
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class AnalysisConversationSummaryResponse(StrictContract):
    id: uuid.UUID
    title: str = Field(min_length=1, max_length=300)
    status: ConversationStatus
    active_turn_id: uuid.UUID | None
    active_turn_status: TurnStatus | None
    last_turn_sequence: int = Field(ge=0)
    last_message_preview: str | None = Field(default=None, max_length=300)
    created_at: datetime
    updated_at: datetime


class AnalysisTurnResponse(StrictContract):
    id: uuid.UUID
    sequence: int = Field(ge=1)
    parent_turn_id: uuid.UUID | None
    analysis_run_id: uuid.UUID | None
    relation: TurnRelation
    status: TurnStatus
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AnalysisConversationPage(StrictContract):
    items: list[AnalysisConversationSummaryResponse] = Field(max_length=100)
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


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


class AnalysisConversationTurnViewResponse(StrictContract):
    turn: AnalysisTurnResponse
    analysis: AnalysisRunViewResponse


class AnalysisConversationViewResponse(StrictContract):
    conversation: AnalysisConversationResponse
    turns: list[AnalysisConversationTurnViewResponse] = Field(max_length=100)
    total_turns: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    read_only: bool = False
    legacy_run_id: uuid.UUID | None = None
