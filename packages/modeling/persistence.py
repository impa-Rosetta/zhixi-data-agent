"""Workspace-scoped modeling receipts and jobs; never store raw training rows."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from packages.platform_core.database import Base


class TrainingSnapshotRecord(Base):
    __tablename__ = "model_training_snapshots"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_model_snapshot_workspace_id"),
        UniqueConstraint("workspace_id", "object_key", name="uq_model_snapshot_object_key"),
        CheckConstraint("size_bytes > 0 AND size_bytes <= 20971520", name="ck_model_snapshot_size"),
        Index("ix_model_snapshot_workspace_created", "workspace_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    source_artifact_id: Mapped[uuid.UUID] = mapped_column()
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column()
    evidence_id: Mapped[uuid.UUID] = mapped_column()
    source_digest: Mapped[str] = mapped_column(String(64))
    content_digest: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    object_key: Mapped[str] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelJob(Base):
    __tablename__ = "model_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "training_snapshot_id"],
            ["model_training_snapshots.workspace_id", "model_training_snapshots.id"],
            ondelete="RESTRICT",
            name="fk_model_job_workspace_snapshot",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_model_job_workspace_id"),
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_model_job_idempotency"),
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled')",
            name="ck_model_job_status",
        ),
        CheckConstraint("operation IN ('train','predict')", name="ck_model_job_operation"),
        CheckConstraint("attempt_count >= 0", name="ck_model_job_attempt_count"),
        Index("ix_model_job_workspace_status", "workspace_id", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    training_snapshot_id: Mapped[uuid.UUID] = mapped_column()
    idempotency_key: Mapped[str] = mapped_column(String(100))
    operation: Mapped[str] = mapped_column(String(10), default="train")
    status: Mapped[str] = mapped_column(String(12), default="queued")
    spec: Mapped[dict[str, object]] = mapped_column(JSON)
    spec_digest: Mapped[str] = mapped_column(String(64))
    attempt_id: Mapped[uuid.UUID | None] = mapped_column()
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RegisteredModel(Base):
    __tablename__ = "registered_models"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_registered_model_workspace_id"),
        UniqueConstraint("workspace_id", "name", name="uq_registered_model_workspace_name"),
        Index("ix_registered_model_workspace_created", "workspace_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "registered_model_id"],
            ["registered_models.workspace_id", "registered_models.id"],
            ondelete="RESTRICT",
            name="fk_model_version_workspace_model",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "training_job_id"],
            ["model_jobs.workspace_id", "model_jobs.id"],
            ondelete="RESTRICT",
            name="fk_model_version_workspace_job",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_model_version_workspace_id"),
        UniqueConstraint("training_job_id", name="uq_model_version_training_job"),
        UniqueConstraint("registered_model_id", "version_number", name="uq_model_version_number"),
        CheckConstraint("version_number > 0", name="ck_model_version_number"),
        CheckConstraint("size_bytes > 0 AND size_bytes <= 20971520", name="ck_model_version_size"),
        Index("ix_model_version_workspace_model", "workspace_id", "registered_model_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    registered_model_id: Mapped[uuid.UUID] = mapped_column()
    training_job_id: Mapped[uuid.UUID] = mapped_column()
    version_number: Mapped[int] = mapped_column(Integer)
    result: Mapped[dict[str, object]] = mapped_column(JSON)
    feature_types: Mapped[dict[str, str]] = mapped_column(JSON)
    model_digest: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    object_key: Mapped[str] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
