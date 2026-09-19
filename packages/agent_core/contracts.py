"""Strict, provider-independent Agent planning contracts."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

AnalysisRoute = Literal[
    "small_talk",
    "capability_help",
    "catalog_exploration",
    "metric_query",
    "comparison",
    "ranking",
    "trend",
    "unsupported",
]
FollowUpRelation = Literal["continue", "refine", "explain", "compare", "switch_topic"]


class Intent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain: str = "manufacturing_quality"
    task_type: Literal[
        "small_talk",
        "capability_help",
        "catalog_exploration",
        "metric_query",
        "comparison",
        "ranking",
        "trend",
        "exploration",
        "clarification",
        "unsupported",
    ]
    goal: str = Field(min_length=2, max_length=1000)
    metrics: tuple[str, ...] = ()
    dimensions: tuple[str, ...] = ()
    filters: dict[str, str | int | float | bool] = Field(default_factory=dict)
    time_range: str | None = None
    comparison: str | None = None
    output: tuple[str, ...] = ("table",)
    ambiguities: tuple[str, ...] = ()
    confidence: float = Field(ge=0, le=1)


class ClarificationCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=500)


class ClarificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_.]{2,99}$")
    question: str = Field(min_length=2, max_length=1000)
    missing_fields: tuple[str, ...] = ()
    candidates: tuple[ClarificationCandidate, ...] = Field(default=(), max_length=20)
    suggested_answers: tuple[str, ...] = Field(default=(), max_length=3)
    resume_node: Literal["understand", "route", "bind", "plan"] = "route"


class RouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    route: AnalysisRoute
    requires_binding: bool
    defaults_applied: dict[str, str] = Field(default_factory=dict)
    clarification: ClarificationRequest | None = None


class ContextPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metrics: tuple[str, ...] | None = None
    dimensions: tuple[str, ...] | None = None
    filters: dict[str, str | int | float | bool] | None = None
    time_range: str | None = None
    comparison: str | None = None
    output: tuple[str, ...] | None = None

    def apply(self, intent: Intent) -> Intent:
        updates = self.model_dump(exclude_none=True)
        if "filters" in updates:
            updates["filters"] = {**intent.filters, **updates["filters"]}
        return intent.model_copy(update=updates)


class IntentRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["patch", "replace"]
    patch: ContextPatch | None = None
    replacement: Intent | None = None

    @model_validator(mode="after")
    def require_exact_revision_payload(self) -> Self:
        valid_patch = self.mode == "patch" and self.patch is not None and self.replacement is None
        valid_replace = (
            self.mode == "replace" and self.replacement is not None and self.patch is None
        )
        if not (valid_patch or valid_replace):
            raise ValueError("intent revision must contain exactly the selected payload")
        return self

    def apply(self, intent: Intent) -> Intent:
        if self.mode == "replace":
            assert self.replacement is not None
            return self.replacement
        assert self.patch is not None
        return self.patch.apply(intent)


class FollowUpDecision(BaseModel):
    """A model-safe classification; it cannot select tools or carry executable content."""

    model_config = ConfigDict(extra="forbid")
    relation: FollowUpRelation
    patch: ContextPatch | None = None
    needs_clarification: bool = False
    clarification_question: str | None = Field(default=None, min_length=2, max_length=500)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_clarification(self) -> Self:
        if self.needs_clarification != (self.clarification_question is not None):
            raise ValueError("clarification flag and question must be provided together")
        if self.relation == "switch_topic" and self.patch is not None:
            raise ValueError("topic switches cannot inherit a context patch")
        return self


class AnalysisStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    tool: str = Field(pattern=r"^[a-z][a-z0-9_.]{2,63}$")
    arguments: dict[str, object] = Field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    expected_evidence: tuple[str, ...] = Field(min_length=1)
    completion_condition: str = "tool_succeeded"

    @model_validator(mode="after")
    def reject_uncontrolled_execution(self) -> Self:
        forbidden = {"sql", "python", "code", "shell", "script", "formula", "credentials"}
        keys = {str(key).lower() for key in self.arguments}
        if keys & forbidden:
            raise ValueError("plan contains an uncontrolled execution field")
        return self


class AnalysisPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str = Field(min_length=2, max_length=1000)
    steps: tuple[AnalysisStep, ...] = Field(min_length=1, max_length=20)
    requires_confirmation: bool = False
    max_replans: int = Field(default=1, ge=0, le=1)

    @model_validator(mode="after")
    def validate_dependency_graph(self) -> Self:
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step ids must be unique")
        known: set[str] = set()
        for step in self.steps:
            if any(dependency not in known for dependency in step.depends_on):
                raise ValueError("step dependencies must reference an earlier step")
            known.add(step.id)
        return self


class AgentBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_model_calls: int = Field(default=6, ge=1, le=20)
    max_tool_calls: int = Field(default=12, ge=1, le=50)
    max_total_tokens: int = Field(default=32_000, ge=1000, le=500_000)
    max_runtime_seconds: int = Field(default=300, ge=10, le=3600)
    max_replans: int = Field(default=1, ge=0, le=1)


class Binding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    semantic_model_id: str
    semantic_version_id: str
    snapshot_ids: tuple[str, ...]
    metric_keys: tuple[str, ...]
    dimension_keys: tuple[str, ...]
    time_dimension_key: str | None = None
    confidence: float = Field(ge=0, le=1)


class AgentGraphState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    message: str
    status: str = "running"
    current_node: str = "understand"
    intent: dict[str, object] | None = None
    binding: dict[str, object] | None = None
    plan: dict[str, object] | None = None
    tool_results: list[dict[str, object]] = Field(default_factory=list)
    error_code: str | None = None
    replans: int = 0
