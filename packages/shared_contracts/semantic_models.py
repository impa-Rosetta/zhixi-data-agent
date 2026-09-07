import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Key = str


class AttributeDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: Key = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    name: str = Field(min_length=1, max_length=120)
    data_type: Literal["string", "number", "integer", "boolean", "date", "datetime"]
    is_identifier: bool = False
    nullable: bool = True


class EntityDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: Key = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    attributes: list[AttributeDefinition] = Field(min_length=1, max_length=100)

    @field_validator("attributes")
    @classmethod
    def unique_attributes(cls, values: list[AttributeDefinition]) -> list[AttributeDefinition]:
        if len({item.key for item in values}) != len(values):
            raise ValueError("Attribute keys must be unique within an entity")
        return values


class RelationshipDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: Key = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    name: str = Field(min_length=1, max_length=120)
    from_attribute: str
    to_attribute: str
    cardinality: Literal["one_to_one", "one_to_many", "many_to_one"]


class DimensionDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: Key = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    name: str = Field(min_length=1, max_length=120)
    entity_key: Key
    attribute_key: Key
    dimension_type: Literal["categorical", "temporal", "geographic"]
    aliases: list[str] = Field(default_factory=list, max_length=20)


class MetricFormula(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["sum", "count", "count_distinct", "average", "min", "max", "ratio_of_sums"]
    attribute: str | None = None
    numerator: str | None = None
    denominator: str | None = None
    scale: float = Field(default=1, gt=0, le=1_000_000)
    zero_division: Literal["null"] = "null"

    @model_validator(mode="after")
    def formula_shape(self) -> "MetricFormula":
        if self.type == "ratio_of_sums":
            if not self.numerator or not self.denominator or self.attribute:
                raise ValueError("ratio_of_sums requires numerator and denominator only")
        elif self.type == "count":
            if self.numerator or self.denominator:
                raise ValueError("count does not accept numerator or denominator")
        elif not self.attribute or self.numerator or self.denominator:
            raise ValueError(f"{self.type} requires attribute only")
        return self


class MetricDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: Key = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1000)
    formula: MetricFormula
    unit: str = Field(min_length=1, max_length=32)
    time_grain: Literal["hour", "day", "week", "month", "quarter", "year"] | None = None
    supported_dimensions: list[Key] = Field(default_factory=list, max_length=30)
    aliases: list[str] = Field(default_factory=list, max_length=20)


class PhysicalMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    semantic_attribute: str
    snapshot_id: uuid.UUID
    relation_id: uuid.UUID
    column_id: uuid.UUID
    confirmed: bool = False
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=500)


class SemanticDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entities: list[EntityDefinition] = Field(default_factory=list, max_length=50)
    relationships: list[RelationshipDefinition] = Field(default_factory=list, max_length=100)
    dimensions: list[DimensionDefinition] = Field(default_factory=list, max_length=100)
    metrics: list[MetricDefinition] = Field(default_factory=list, max_length=100)
    mappings: list[PhysicalMapping] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def unique_keys(self) -> "SemanticDocument":
        for label, values in (
            ("entity", self.entities),
            ("relationship", self.relationships),
            ("dimension", self.dimensions),
            ("metric", self.metrics),
        ):
            keys = [item.key for item in values]
            if len(set(keys)) != len(keys):
                raise ValueError(f"Duplicate {label} key")
        refs = [item.semantic_attribute for item in self.mappings]
        if len(set(refs)) != len(refs):
            raise ValueError("Each semantic attribute can have only one physical mapping")
        return self


class SemanticModelCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name must not be blank")
        return value


class SemanticDraftUpdateRequest(SemanticDocument):
    version: int = Field(ge=1)


class SemanticVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)


class SemanticModelResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    description: str | None
    status: str
    version: int
    draft_revision: int
    published_version: int | None
    counts: dict[str, int]
    document: SemanticDocument
    content_digest: str
    created_at: datetime
    updated_at: datetime


class SemanticModelPage(BaseModel):
    items: list[SemanticModelResponse]
    total: int


class MappingCandidate(BaseModel):
    semantic_attribute: str
    snapshot_id: uuid.UUID
    relation_id: uuid.UUID
    column_id: uuid.UUID
    schema_name: str
    relation_name: str
    column_name: str
    confidence: float
    reason: str


class MappingCandidateResponse(BaseModel):
    snapshot_id: uuid.UUID
    candidates: list[MappingCandidate]
    unmapped_attributes: list[str]
