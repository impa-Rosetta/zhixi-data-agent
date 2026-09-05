import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from packages.platform_core.models import (
    DataSourceStatus,
    DataSourceType,
    ScanJobStatus,
    ScanJobTrigger,
    ScanJobType,
    SnapshotStatus,
    TlsMode,
)


class DataSourceCredentialsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)
    tls_ca_certificate: str | None = Field(default=None, max_length=64_000)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Username must not be blank")
        return normalized


class DataSourceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2_000)
    source_type: DataSourceType
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65_535)
    database_name: str = Field(min_length=1, max_length=128)
    tls_mode: TlsMode = TlsMode.REQUIRE
    network_policy_id: uuid.UUID | None = None
    credentials: DataSourceCredentialsRequest

    @field_validator("name", "database_name")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_ca_requirements(self) -> "DataSourceCreateRequest":
        if self.tls_mode in {TlsMode.VERIFY_CA, TlsMode.VERIFY_FULL} and not (
            self.credentials.tls_ca_certificate
        ):
            raise ValueError("A CA certificate is required for TLS verification")
        return self


class DataSourceUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2_000)
    host: str | None = Field(default=None, min_length=1, max_length=253)
    port: int | None = Field(default=None, ge=1, le=65_535)
    database_name: str | None = Field(default=None, min_length=1, max_length=128)
    tls_mode: TlsMode | None = None
    network_policy_id: uuid.UUID | None = None
    credentials: DataSourceCredentialsRequest | None = None

    @field_validator("name", "database_name")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value must not be blank")
        return normalized


class ScanJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    data_source_id: uuid.UUID
    snapshot_id: uuid.UUID | None
    job_type: ScanJobType
    trigger: ScanJobTrigger
    status: ScanJobStatus
    phase: str | None
    progress: int
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class DataSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    description: str | None
    source_type: DataSourceType
    host: str
    port: int
    database_name: str
    tls_mode: TlsMode
    network_policy_id: uuid.UUID | None
    status: DataSourceStatus
    health_code: str | None
    active_snapshot_id: uuid.UUID | None
    version: int
    last_checked_at: datetime | None
    last_success_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DataSourceCreateResponse(BaseModel):
    data_source: DataSourceResponse
    job: ScanJobResponse


class VersionRequest(BaseModel):
    version: int = Field(ge=1)


class DataSourcePage(BaseModel):
    items: list[DataSourceResponse]
    total: int
    limit: int
    offset: int


class ErrorDetail(BaseModel):
    code: str
    message: str


class MetadataScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schemas: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("schemas")
    @classmethod
    def validate_schemas(cls, values: list[str]) -> list[str]:
        normalized = [item.strip() for item in values]
        if any(not item or len(item) > 128 for item in normalized):
            raise ValueError("Schema names must contain 1 to 128 characters")
        if any(item == "information_schema" or item.startswith("pg_") for item in normalized):
            raise ValueError("System schemas cannot be selected")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Schema names must be unique")
        return normalized


class CatalogSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    data_source_id: uuid.UUID
    version: int
    status: SnapshotStatus
    database_product: str
    database_version: str | None
    scan_options: dict[str, object]
    object_counts: dict[str, object]
    content_digest: str | None
    sampling_enabled: bool
    started_at: datetime
    completed_at: datetime | None


class CatalogColumnResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    ordinal_position: int
    data_type: str
    native_type: str
    nullable: bool
    default_expression: str | None
    comment: str | None


class CatalogConstraintResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    constraint_type: str
    columns: tuple[str, ...]
    referenced_schema: str | None
    referenced_relation: str | None
    referenced_columns: tuple[str, ...]


class CatalogIndexResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    columns: tuple[str, ...]
    unique: bool
    method: str | None
    predicate: str | None


class CatalogRelationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    relation_type: str
    comment: str | None
    columns: list[CatalogColumnResponse]
    constraints: list[CatalogConstraintResponse]
    indexes: list[CatalogIndexResponse]


class CatalogSchemaResponse(BaseModel):
    name: str
    comment: str | None
    relations: list[CatalogRelationResponse]


class CatalogResponse(BaseModel):
    snapshot: CatalogSnapshotResponse
    schemas: list[CatalogSchemaResponse]


class CatalogDiffResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    from_snapshot_id: uuid.UUID | None
    to_snapshot_id: uuid.UUID
    change_type: str
    object_type: str
    object_key: str
    severity: str
    before_value: dict[str, object] | None
    after_value: dict[str, object] | None


class CatalogDiffPage(BaseModel):
    items: list[CatalogDiffResponse]
    total: int
    limit: int
    offset: int
