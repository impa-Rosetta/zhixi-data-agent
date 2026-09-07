import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from packages.platform_core.database import Base


class QueryTrust(enum.StrEnum):
    TRUSTED = "trusted"
    EXPLORATORY = "exploratory"


class QueryExecutionStatus(enum.StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


def _enum_values(enum_type: type[enum.Enum]) -> list[str]:
    return [str(item.value) for item in enum_type]


class ValidatedQuery(Base):
    __tablename__ = "validated_queries"
    __table_args__ = (Index("ix_validated_query_workspace_created", "workspace_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    data_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT"), index=True
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_snapshots.id", ondelete="RESTRICT"), index=True
    )
    semantic_model_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("semantic_models.id", ondelete="SET NULL"), index=True
    )
    semantic_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("semantic_model_versions.id", ondelete="SET NULL"), index=True
    )
    dialect: Mapped[str] = mapped_column(String(20))
    trust: Mapped[QueryTrust] = mapped_column(
        Enum(QueryTrust, name="query_trust", native_enum=False, values_callable=_enum_values),
        index=True,
    )
    protocol: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    sql_text: Mapped[str] = mapped_column(Text)
    parameters: Mapped[list[object]] = mapped_column(JSON, default=list)
    dependencies: Mapped[list[str]] = mapped_column(JSON, default=list)
    safety_report: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    digest: Mapped[str] = mapped_column(String(64), index=True)
    row_limit: Mapped[int] = mapped_column(Integer)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QueryExecution(Base):
    __tablename__ = "query_executions"
    __table_args__ = (Index("ix_query_execution_workspace_started", "workspace_id", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    validated_query_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("validated_queries.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[QueryExecutionStatus] = mapped_column(
        Enum(
            QueryExecutionStatus,
            name="query_execution_status",
            native_enum=False,
            values_callable=_enum_values,
        ),
        index=True,
    )
    columns: Mapped[list[str]] = mapped_column(JSON, default=list)
    rows: Mapped[list[list[object]]] = mapped_column(JSON, default=list)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    truncated: Mapped[bool] = mapped_column(default=False)
    result_digest: Mapped[str | None] = mapped_column(String(64))
    evidence_digest: Mapped[str | None] = mapped_column(String(64), index=True)
    evidence: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(100))
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
