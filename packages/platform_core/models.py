import enum
import uuid
from datetime import datetime, time

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from packages.platform_core.database import Base


class WorkspaceRole(enum.StrEnum):
    SYSTEM_ADMIN = "system_admin"
    WORKSPACE_ADMIN = "workspace_admin"
    DATA_ADMIN = "data_admin"
    ANALYST = "analyst"
    AUDITOR = "auditor"


class DataSourceType(enum.StrEnum):
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"


class DataSourceStatus(enum.StrEnum):
    DRAFT = "draft"
    TESTING = "testing"
    READY = "ready"
    DEGRADED = "degraded"
    DISABLED = "disabled"
    DELETED = "deleted"


class TlsMode(enum.StrEnum):
    DISABLE = "disable"
    PREFER = "prefer"
    REQUIRE = "require"
    VERIFY_CA = "verify_ca"
    VERIFY_FULL = "verify_full"


class ScanJobType(enum.StrEnum):
    CONNECTION_TEST = "connection_test"
    METADATA_SCAN = "metadata_scan"
    PROFILE_SCAN = "profile_scan"


class ScanJobTrigger(enum.StrEnum):
    INITIAL = "initial"
    MANUAL = "manual"
    SCHEDULED = "scheduled"


class ScanJobStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SnapshotStatus(enum.StrEnum):
    BUILDING = "building"
    PUBLISHED = "published"
    REJECTED = "rejected"


class ProfilingStatus(enum.StrEnum):
    DISABLED = "disabled"
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScheduleFrequency(enum.StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"


def _enum_values(enum_type: type[enum.Enum]) -> list[str]:
    return [str(item.value) for item in enum_type]


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user")


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    memberships: Mapped[list["Membership"]] = relationship(back_populates="workspace")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_membership_workspace_user"),
        Index("ix_membership_user_workspace", "user_id", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[WorkspaceRole] = mapped_column(
        Enum(WorkspaceRole, name="workspace_role", native_enum=False)
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    workspace: Mapped[Workspace] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("refresh_sessions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspaceInvitation(Base):
    __tablename__ = "workspace_invitations"
    __table_args__ = (Index("ix_invitation_workspace_email", "workspace_id", "email"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[WorkspaceRole] = mapped_column(
        Enum(WorkspaceRole, name="workspace_role", native_enum=False)
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invited_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(100), index=True)
    resource_type: Mapped[str] = mapped_column(String(100))
    resource_id: Mapped[str | None] = mapped_column(String(100))
    outcome: Mapped[str] = mapped_column(String(20))
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class NetworkPolicy(Base):
    __tablename__ = "network_policies"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_network_policy_workspace_name"),
        Index(
            "uq_network_policy_default_workspace",
            "workspace_id",
            unique=True,
            postgresql_where=text("is_default"),
            sqlite_where=text("is_default = 1"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    allowed_private_cidrs: Mapped[list[str]] = mapped_column(JSON, default=list)
    allowed_ports: Mapped[list[int]] = mapped_column(JSON, default=lambda: [5432, 3306])
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DataSource(Base):
    __tablename__ = "data_sources"
    __table_args__ = (
        Index(
            "uq_data_source_workspace_name",
            "workspace_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        CheckConstraint("port >= 1 AND port <= 65535", name="ck_data_source_port"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    network_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("network_policies.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[DataSourceType] = mapped_column(
        Enum(
            DataSourceType,
            name="data_source_type",
            native_enum=False,
            values_callable=_enum_values,
        )
    )
    host: Mapped[str] = mapped_column(String(253))
    port: Mapped[int] = mapped_column(Integer)
    database_name: Mapped[str] = mapped_column(String(128))
    tls_mode: Mapped[TlsMode] = mapped_column(
        Enum(TlsMode, name="tls_mode", native_enum=False, values_callable=_enum_values)
    )
    status: Mapped[DataSourceStatus] = mapped_column(
        Enum(
            DataSourceStatus,
            name="data_source_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        default=DataSourceStatus.DRAFT,
        index=True,
    )
    health_code: Mapped[str | None] = mapped_column(String(100))
    active_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "catalog_snapshots.id",
            name="fk_data_source_active_snapshot",
            ondelete="SET NULL",
            use_alter=True,
        )
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DataSourceSecret(Base):
    __tablename__ = "data_source_secrets"

    data_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_sources.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(String(50), default="local_envelope")
    algorithm: Mapped[str] = mapped_column(String(30))
    format_version: Mapped[int] = mapped_column(Integer)
    key_version: Mapped[str] = mapped_column(String(50))
    wrapped_data_key: Mapped[str] = mapped_column(Text)
    key_nonce: Mapped[str] = mapped_column(String(64))
    ciphertext: Mapped[str] = mapped_column(Text)
    payload_nonce: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    destroyed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ScanJob(Base):
    __tablename__ = "scan_jobs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_scan_job_idempotency"),
        CheckConstraint("progress >= 0 AND progress <= 100", name="ck_scan_job_progress"),
        Index(
            "uq_scan_job_active_source",
            "data_source_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
            sqlite_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    data_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_sources.id", ondelete="CASCADE"), index=True
    )
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog_snapshots.id", ondelete="SET NULL"), index=True
    )
    parent_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scan_jobs.id", ondelete="SET NULL"), index=True
    )
    retry_of_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scan_jobs.id", ondelete="SET NULL"), index=True
    )
    job_type: Mapped[ScanJobType] = mapped_column(
        Enum(
            ScanJobType,
            name="scan_job_type",
            native_enum=False,
            values_callable=_enum_values,
        )
    )
    trigger: Mapped[ScanJobTrigger] = mapped_column(
        Enum(
            ScanJobTrigger,
            name="scan_job_trigger",
            native_enum=False,
            values_callable=_enum_values,
        )
    )
    status: Mapped[ScanJobStatus] = mapped_column(
        Enum(
            ScanJobStatus,
            name="scan_job_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(100))
    celery_task_id: Mapped[str | None] = mapped_column(String(100))
    phase: Mapped[str | None] = mapped_column(String(100))
    progress: Mapped[int] = mapped_column(Integer, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(100))
    parameters: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    aggregate_type: Mapped[str] = mapped_column(String(100))
    aggregate_id: Mapped[uuid.UUID] = mapped_column(index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CatalogSnapshot(Base):
    __tablename__ = "catalog_snapshots"
    __table_args__ = (
        UniqueConstraint("data_source_id", "version", name="uq_catalog_snapshot_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    data_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_sources.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[SnapshotStatus] = mapped_column(
        Enum(
            SnapshotStatus,
            name="snapshot_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        index=True,
    )
    database_product: Mapped[str] = mapped_column(String(50))
    database_version: Mapped[str | None] = mapped_column(String(100))
    scan_options: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    object_counts: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    content_digest: Mapped[str | None] = mapped_column(String(64))
    sampling_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    profiling_status: Mapped[ProfilingStatus] = mapped_column(
        Enum(
            ProfilingStatus,
            name="profiling_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        default=ProfilingStatus.DISABLED,
        index=True,
    )
    profiling_error_code: Mapped[str | None] = mapped_column(String(100))
    profiling_options: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    profile_counts: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    profiling_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    profiling_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SamplingPolicy(Base):
    __tablename__ = "sampling_policies"
    __table_args__ = (
        CheckConstraint("max_rows_per_table >= 1 AND max_rows_per_table <= 20"),
        CheckConstraint("max_values_per_column >= 1 AND max_values_per_column <= 20"),
        CheckConstraint("max_value_chars >= 16 AND max_value_chars <= 256"),
        CheckConstraint("max_bytes_per_table >= 1024"),
        CheckConstraint("max_bytes_per_job >= max_bytes_per_table"),
        CheckConstraint("statement_timeout_seconds >= 1 AND statement_timeout_seconds <= 10"),
    )

    data_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_sources.id", ondelete="CASCADE"), primary_key=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    schema_allowlist: Mapped[list[str]] = mapped_column(JSON, default=list)
    table_allowlist: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    max_rows_per_table: Mapped[int] = mapped_column(Integer, default=20)
    max_values_per_column: Mapped[int] = mapped_column(Integer, default=20)
    max_value_chars: Mapped[int] = mapped_column(Integer, default=256)
    max_bytes_per_table: Mapped[int] = mapped_column(Integer, default=65_536)
    max_bytes_per_job: Mapped[int] = mapped_column(Integer, default=1_048_576)
    statement_timeout_seconds: Mapped[int] = mapped_column(Integer, default=10)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ScanSchedule(Base):
    __tablename__ = "scan_schedules"
    __table_args__ = (
        CheckConstraint("day_of_week IS NULL OR (day_of_week >= 0 AND day_of_week <= 6)"),
    )

    data_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_sources.id", ondelete="CASCADE"), primary_key=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    frequency: Mapped[ScheduleFrequency] = mapped_column(
        Enum(
            ScheduleFrequency,
            name="schedule_frequency",
            native_enum=False,
            values_callable=_enum_values,
        )
    )
    timezone: Mapped[str] = mapped_column(String(64))
    local_time: Mapped[time] = mapped_column(Time())
    day_of_week: Mapped[int | None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CatalogSchema(Base):
    __tablename__ = "catalog_schemas"
    __table_args__ = (UniqueConstraint("snapshot_id", "stable_key", name="uq_catalog_schema_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    data_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_sources.id", ondelete="CASCADE"), index=True
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_snapshots.id", ondelete="CASCADE"), index=True
    )
    stable_key: Mapped[str] = mapped_column(String(700))
    name: Mapped[str] = mapped_column(String(128))
    normalized_name: Mapped[str] = mapped_column(String(128), index=True)
    comment: Mapped[str | None] = mapped_column(Text)


class CatalogRelation(Base):
    __tablename__ = "catalog_relations"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "stable_key", name="uq_catalog_relation_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    data_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_sources.id", ondelete="CASCADE"), index=True
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_snapshots.id", ondelete="CASCADE"), index=True
    )
    schema_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_schemas.id", ondelete="CASCADE"), index=True
    )
    stable_key: Mapped[str] = mapped_column(String(700))
    name: Mapped[str] = mapped_column(String(128))
    normalized_name: Mapped[str] = mapped_column(String(128), index=True)
    relation_type: Mapped[str] = mapped_column(String(32))
    comment: Mapped[str | None] = mapped_column(Text)


class CatalogColumn(Base):
    __tablename__ = "catalog_columns"
    __table_args__ = (UniqueConstraint("snapshot_id", "stable_key", name="uq_catalog_column_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    data_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_sources.id", ondelete="CASCADE"), index=True
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_snapshots.id", ondelete="CASCADE"), index=True
    )
    relation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_relations.id", ondelete="CASCADE"), index=True
    )
    stable_key: Mapped[str] = mapped_column(String(700))
    name: Mapped[str] = mapped_column(String(128))
    normalized_name: Mapped[str] = mapped_column(String(128), index=True)
    ordinal_position: Mapped[int] = mapped_column(Integer)
    data_type: Mapped[str] = mapped_column(String(64), index=True)
    native_type: Mapped[str] = mapped_column(String(256))
    nullable: Mapped[bool] = mapped_column(Boolean)
    default_expression: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)


class CatalogColumnProfile(Base):
    __tablename__ = "catalog_column_profiles"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "column_id", name="uq_catalog_column_profile"),
        CheckConstraint("sensitivity_confidence >= 0 AND sensitivity_confidence <= 1"),
        CheckConstraint(
            "sample_null_rate IS NULL OR (sample_null_rate >= 0 AND sample_null_rate <= 1)"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    data_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_sources.id", ondelete="CASCADE"), index=True
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_snapshots.id", ondelete="CASCADE"), index=True
    )
    column_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_columns.id", ondelete="CASCADE"), index=True
    )
    sample_row_count: Mapped[int] = mapped_column(Integer, default=0)
    non_null_count: Mapped[int] = mapped_column(Integer, default=0)
    estimated_row_count: Mapped[int | None] = mapped_column(Integer)
    sample_null_rate: Mapped[float | None] = mapped_column(Float)
    sampled_distinct_count: Mapped[int | None] = mapped_column(Integer)
    minimum_value: Mapped[str | None] = mapped_column(Text)
    maximum_value: Mapped[str | None] = mapped_column(Text)
    minimum_length: Mapped[int | None] = mapped_column(Integer)
    maximum_length: Mapped[int | None] = mapped_column(Integer)
    average_length: Mapped[float | None] = mapped_column(Float)
    sensitivity_type: Mapped[str | None] = mapped_column(String(50), index=True)
    sensitivity_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    sensitivity_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    metric_sources: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CatalogSample(Base):
    __tablename__ = "catalog_samples"
    __table_args__ = (
        UniqueConstraint("column_profile_id", "ordinal", name="uq_catalog_sample_ordinal"),
        CheckConstraint("ordinal >= 1 AND ordinal <= 20"),
        CheckConstraint("byte_count >= 0"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    data_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_sources.id", ondelete="CASCADE"), index=True
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_snapshots.id", ondelete="CASCADE"), index=True
    )
    column_profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_column_profiles.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    masked_value: Mapped[str] = mapped_column(String(256))
    value_type: Mapped[str] = mapped_column(String(32))
    byte_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CatalogConstraint(Base):
    __tablename__ = "catalog_constraints"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "stable_key", name="uq_catalog_constraint_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    data_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_sources.id", ondelete="CASCADE"), index=True
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_snapshots.id", ondelete="CASCADE"), index=True
    )
    relation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_relations.id", ondelete="CASCADE"), index=True
    )
    stable_key: Mapped[str] = mapped_column(String(700))
    name: Mapped[str] = mapped_column(String(128))
    constraint_type: Mapped[str] = mapped_column(String(32), index=True)
    column_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    referenced_schema: Mapped[str | None] = mapped_column(String(128))
    referenced_relation: Mapped[str | None] = mapped_column(String(128))
    referenced_columns: Mapped[list[str]] = mapped_column(JSON, default=list)


class CatalogIndex(Base):
    __tablename__ = "catalog_indexes"
    __table_args__ = (UniqueConstraint("snapshot_id", "stable_key", name="uq_catalog_index_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    data_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_sources.id", ondelete="CASCADE"), index=True
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_snapshots.id", ondelete="CASCADE"), index=True
    )
    relation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_relations.id", ondelete="CASCADE"), index=True
    )
    stable_key: Mapped[str] = mapped_column(String(700))
    name: Mapped[str] = mapped_column(String(128))
    column_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_unique: Mapped[bool] = mapped_column(Boolean)
    method: Mapped[str | None] = mapped_column(String(64))
    predicate: Mapped[str | None] = mapped_column(Text)


class CatalogDiff(Base):
    __tablename__ = "catalog_diffs"
    __table_args__ = (
        UniqueConstraint(
            "from_snapshot_id",
            "to_snapshot_id",
            "object_key",
            "change_type",
            name="uq_catalog_diff_change",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    data_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_sources.id", ondelete="CASCADE"), index=True
    )
    from_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog_snapshots.id", ondelete="CASCADE"), index=True
    )
    to_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_snapshots.id", ondelete="CASCADE"), index=True
    )
    change_type: Mapped[str] = mapped_column(String(32), index=True)
    object_type: Mapped[str] = mapped_column(String(32), index=True)
    object_key: Mapped[str] = mapped_column(String(700))
    severity: Mapped[str] = mapped_column(String(32), index=True)
    before_value: Mapped[dict[str, object] | None] = mapped_column(JSON)
    after_value: Mapped[dict[str, object] | None] = mapped_column(JSON)
