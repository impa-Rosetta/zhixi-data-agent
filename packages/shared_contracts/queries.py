import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Scalar = str | int | float | bool | date | datetime


class QueryFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dimension: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    operator: Literal["eq", "neq", "gt", "gte", "lt", "lte", "in", "not_in", "between"]
    value: Scalar | list[Scalar]

    @model_validator(mode="after")
    def valid_shape(self) -> "QueryFilter":
        is_list = isinstance(self.value, list)
        if self.operator in {"in", "not_in"} and (not is_list or not self.value):
            raise ValueError("in/not_in requires a non-empty list")
        if self.operator == "between" and (
            not isinstance(self.value, list) or len(self.value) != 2
        ):
            raise ValueError("between requires exactly two values")
        if self.operator not in {"in", "not_in", "between"} and is_list:
            raise ValueError("scalar operator requires a scalar value")
        return self


class QuerySort(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    direction: Literal["asc", "desc"] = "desc"


class SemanticQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    semantic_model_id: uuid.UUID
    metrics: list[str] = Field(min_length=1, max_length=10)
    dimensions: list[str] = Field(default_factory=list, max_length=8)
    filters: list[QueryFilter] = Field(default_factory=list, max_length=20)
    time_grain: Literal["hour", "day", "week", "month", "quarter", "year"] | None = None
    comparison: Literal["none", "previous_period"] = "none"
    sort: list[QuerySort] = Field(default_factory=list, max_length=5)
    limit: int = Field(default=200, ge=1, le=1000)

    @model_validator(mode="after")
    def unique_fields(self) -> "SemanticQueryRequest":
        if len(set(self.metrics)) != len(self.metrics) or len(set(self.dimensions)) != len(
            self.dimensions
        ):
            raise ValueError("Query fields must be unique")
        if self.time_grain and not self.dimensions:
            raise ValueError("time_grain requires a temporal dimension")
        return self


class ExploratoryQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data_source_id: uuid.UUID
    sql: str = Field(min_length=1, max_length=50_000)
    limit: int = Field(default=200, ge=1, le=1000)


class SafetyFinding(BaseModel):
    code: str
    message: str


class ValidatedQueryResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    data_source_id: uuid.UUID
    semantic_model_id: uuid.UUID | None
    semantic_version_id: uuid.UUID | None
    snapshot_id: uuid.UUID
    dialect: Literal["postgres", "mysql"]
    trust: Literal["trusted", "exploratory"]
    sql: str
    parameter_count: int
    dependencies: list[str]
    digest: str
    safety_findings: list[SafetyFinding]
    expires_at: datetime
    created_at: datetime


class QueryExecutionResponse(BaseModel):
    id: uuid.UUID
    validated_query_id: uuid.UUID
    status: Literal["succeeded", "failed", "cancelled"]
    columns: list[str]
    rows: list[list[object]]
    row_count: int
    truncated: bool
    trust: Literal["trusted", "exploratory"]
    evidence_digest: str | None
    error_code: str | None
    started_at: datetime
    finished_at: datetime
