"""Strict contracts for synthetic golden questions and structured observations."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CaseCategory = Literal["standard", "multi_turn", "ambiguity", "anomaly", "security"]
OutcomeStatus = Literal["completed", "clarification", "denied", "failed"]
SafetyKind = Literal["unauthorized_access", "dangerous_sql"]

CATEGORY_QUOTAS: dict[str, int] = {
    "standard": 60,
    "multi_turn": 20,
    "ambiguity": 20,
    "anomaly": 20,
    "security": 20,
}


class StrictEvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CaseExpectation(StrictEvaluationModel):
    status: OutcomeStatus
    task_type: str | None = Field(default=None, max_length=80)
    metric_ids: tuple[str, ...] = Field(default=(), max_length=20)
    required_tools: tuple[str, ...] = Field(default=(), max_length=20)
    allowed_tools: tuple[str, ...] = Field(default=(), max_length=30)
    numbers: dict[str, Decimal] = Field(default_factory=dict, max_length=30)
    absolute_tolerance: Decimal = Decimal("0")
    require_evidence: bool = False
    safety_kind: SafetyKind | None = None

    @model_validator(mode="after")
    def check_consistency(self) -> CaseExpectation:
        if self.absolute_tolerance < 0 or not self.absolute_tolerance.is_finite():
            raise ValueError("absolute_tolerance must be finite and nonnegative")
        if any(not value.is_finite() for value in self.numbers.values()):
            raise ValueError("expected numbers must be finite")
        if self.safety_kind is not None and self.status != "denied":
            raise ValueError("security cases must expect denied status")
        if not set(self.required_tools).issubset(self.allowed_tools):
            raise ValueError("required_tools must be allowed")
        return self


class EvaluationCase(StrictEvaluationModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,79}$")
    category: CaseCategory
    turns: tuple[str, ...] = Field(min_length=1, max_length=10)
    expected: CaseExpectation
    rationale: str = Field(min_length=5, max_length=1000)

    @field_validator("turns")
    @classmethod
    def validate_turns(cls, turns: tuple[str, ...]) -> tuple[str, ...]:
        if any(not turn.strip() or len(turn) > 2000 for turn in turns):
            raise ValueError("turns must be nonempty and at most 2000 characters")
        return turns

    @model_validator(mode="after")
    def validate_category(self) -> EvaluationCase:
        if self.category == "multi_turn" and len(self.turns) < 2:
            raise ValueError("multi_turn cases need at least two turns")
        if self.category == "security" and self.expected.safety_kind is None:
            raise ValueError("security cases need safety_kind")
        if self.category != "security" and self.expected.safety_kind is not None:
            raise ValueError("safety_kind belongs only to security cases")
        return self


class EvaluationSuite(StrictEvaluationModel):
    schema_version: Literal["1.0"] = "1.0"
    suite_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    synthetic_dataset_id: str = Field(pattern=r"^synthetic-[a-z0-9_-]+$")
    semantic_version: str = Field(min_length=1, max_length=100)
    cases: tuple[EvaluationCase, ...] = Field(min_length=1, max_length=1000)
    published: bool = False

    @model_validator(mode="after")
    def validate_suite(self) -> EvaluationSuite:
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("case IDs must be unique")
        if self.published:
            counts = {category: 0 for category in CATEGORY_QUOTAS}
            for case in self.cases:
                counts[case.category] += 1
            if any(counts[key] < minimum for key, minimum in CATEGORY_QUOTAS.items()):
                raise ValueError("published suite needs at least 60/20/20/20/20 cases")
        return self

    @property
    def content_digest(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ObservedOutcome(StrictEvaluationModel):
    status: OutcomeStatus
    task_type: str | None = None
    metric_ids: tuple[str, ...] = ()
    tool_calls: tuple[str, ...] = ()
    numbers: dict[str, Decimal] = Field(default_factory=dict)
    evidence_numbers: dict[str, Decimal] = Field(default_factory=dict)
    validation_passed: bool = False
    policy_denied: bool = False
    unauthorized_data_accessed: bool = False
    dangerous_sql_executed: bool = False
    infra_error_code: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def finite_numbers(self) -> ObservedOutcome:
        if any(
            not value.is_finite()
            for value in (*self.numbers.values(), *self.evidence_numbers.values())
        ):
            raise ValueError("observed numbers must be finite")
        return self
