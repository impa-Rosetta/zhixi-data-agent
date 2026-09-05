import uuid
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from packages.platform_core.models import (
    DataSourceStatus,
    DataSourceType,
    ProfilingStatus,
    ScanJobStatus,
    ScanJobTrigger,
    ScanJobType,
    ScheduleFrequency,
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
    parent_job_id: uuid.UUID | None
    retry_of_job_id: uuid.UUID | None
    job_type: ScanJobType
    trigger: ScanJobTrigger
    status: ScanJobStatus
    phase: str | None
    progress: int
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    heartbeat_at: datetime | None
    cancel_requested_at: datetime | None
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
    profiling_status: ProfilingStatus
    profiling_error_code: str | None
    profiling_options: dict[str, object]
    profile_counts: dict[str, object]
    profiling_started_at: datetime | None
    profiling_finished_at: datetime | None
    started_at: datetime
    completed_at: datetime | None


class SamplingTableScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_name: str = Field(min_length=1, max_length=128)
    table_name: str = Field(min_length=1, max_length=128)

    @field_validator("schema_name", "table_name")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Identifiers must not be blank")
        return normalized


class SamplingPolicyUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=0)
    enabled: bool = False
    schema_allowlist: list[str] = Field(default_factory=list, max_length=100)
    table_allowlist: list[SamplingTableScope] = Field(default_factory=list, max_length=500)
    max_rows_per_table: int = Field(default=20, ge=1, le=20)
    max_values_per_column: int = Field(default=20, ge=1, le=20)
    max_value_chars: int = Field(default=256, ge=16, le=256)
    max_bytes_per_table: int = Field(default=65_536, ge=1_024, le=1_048_576)
    max_bytes_per_job: int = Field(default=1_048_576, ge=1_024, le=10_485_760)
    statement_timeout_seconds: int = Field(default=10, ge=1, le=10)

    @field_validator("schema_allowlist")
    @classmethod
    def validate_schemas(cls, values: list[str]) -> list[str]:
        normalized = [item.strip() for item in values]
        if any(not item or len(item) > 128 for item in normalized):
            raise ValueError("Schema names must contain 1 to 128 characters")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Schema names must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_scope_and_budget(self) -> "SamplingPolicyUpdateRequest":
        table_keys = [(item.schema_name, item.table_name) for item in self.table_allowlist]
        if len(table_keys) != len(set(table_keys)):
            raise ValueError("Table scopes must be unique")
        schemas = set(self.schema_allowlist)
        if any(schema not in schemas for schema, _ in table_keys):
            raise ValueError("Every table must belong to an allowed schema")
        if self.enabled and not table_keys:
            raise ValueError("Enabled sampling requires at least one table")
        if self.max_bytes_per_job < self.max_bytes_per_table:
            raise ValueError("Job byte budget must cover one table budget")
        return self


class SamplingPolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    data_source_id: uuid.UUID
    enabled: bool
    schema_allowlist: list[str]
    table_allowlist: list[SamplingTableScope]
    max_rows_per_table: int
    max_values_per_column: int
    max_value_chars: int
    max_bytes_per_table: int
    max_bytes_per_job: int
    statement_timeout_seconds: int
    version: int
    updated_at: datetime | None


class ScanScheduleUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=0)
    enabled: bool = False
    frequency: ScheduleFrequency
    timezone: str = Field(min_length=1, max_length=64)
    local_time: time
    day_of_week: int | None = Field(default=None, ge=0, le=6)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        normalized = value.strip()
        try:
            ZoneInfo(normalized)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Timezone must be a valid IANA name") from exc
        return normalized

    @field_validator("local_time")
    @classmethod
    def validate_local_time(cls, value: time) -> time:
        if value.tzinfo is not None:
            raise ValueError("Local execution time must not include an offset")
        return value

    @model_validator(mode="after")
    def validate_frequency(self) -> "ScanScheduleUpdateRequest":
        if self.frequency is ScheduleFrequency.WEEKLY and self.day_of_week is None:
            raise ValueError("Weekly schedules require day_of_week")
        if self.frequency is ScheduleFrequency.DAILY and self.day_of_week is not None:
            raise ValueError("Daily schedules cannot specify day_of_week")
        return self


class ScanScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    data_source_id: uuid.UUID
    enabled: bool
    frequency: ScheduleFrequency
    timezone: str
    local_time: time
    day_of_week: int | None
    next_run_at: datetime | None
    last_enqueued_at: datetime | None
    version: int
    updated_at: datetime | None

    @field_validator("next_run_at", "last_enqueued_at", mode="before")
    @classmethod
    def normalize_utc_datetimes(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


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
