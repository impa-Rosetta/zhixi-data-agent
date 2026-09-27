"""Workspace-scoped evaluation records; never store prompts or provider payloads."""

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


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_evaluation_run_workspace_id"),
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_evaluation_run_idempotency"),
        CheckConstraint("track IN ('offline','live')", name="ck_evaluation_run_track"),
        CheckConstraint(
            "status IN ('queued','running','completed','partial','failed','cancelled')",
            name="ck_evaluation_run_status",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND calls_used >= 0 AND tokens_used >= 0 "
            "AND calls_reserved >= 0 AND tokens_reserved >= 0",
            name="ck_evaluation_run_nonnegative",
        ),
        Index("ix_evaluation_run_workspace_created", "workspace_id", "created_at"),
        Index("ix_evaluation_run_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    idempotency_key: Mapped[str] = mapped_column(String(100))
    track: Mapped[str] = mapped_column(String(10), default="offline")
    status: Mapped[str] = mapped_column(String(12), default="queued")
    suite_version: Mapped[str] = mapped_column(String(32))
    suite_digest: Mapped[str] = mapped_column(String(64))
    dataset_id: Mapped[str] = mapped_column(String(100))
    semantic_version: Mapped[str] = mapped_column(String(100))
    model_version: Mapped[str] = mapped_column(String(100))
    tool_version: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(100))
    budget: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    summary: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    calls_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    tokens_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    calls_reserved: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    tokens_reserved: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class EvaluationCaseResult(Base):
    __tablename__ = "evaluation_case_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "evaluation_run_id"],
            ["evaluation_runs.workspace_id", "evaluation_runs.id"],
            ondelete="CASCADE",
            name="fk_evaluation_case_run_workspace",
        ),
        UniqueConstraint("evaluation_run_id", "case_id", name="uq_evaluation_case_run_id"),
        CheckConstraint(
            "status IN ('queued','running','passed','failed','blocked','infra_error')",
            name="ck_evaluation_case_status",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND duration_ms >= 0", name="ck_evaluation_case_nonnegative"
        ),
        Index("ix_evaluation_case_workspace_run", "workspace_id", "evaluation_run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    evaluation_run_id: Mapped[uuid.UUID] = mapped_column()
    case_id: Mapped[str] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(12), default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    assertion_results: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    run_references: Mapped[list[str]] = mapped_column(JSON, default=list)
    error_code: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvaluationModelCall(Base):
    """A durable receipt, not a cache of provider requests or responses."""

    __tablename__ = "evaluation_model_calls"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "evaluation_run_id"],
            ["evaluation_runs.workspace_id", "evaluation_runs.id"],
            ondelete="CASCADE",
            name="fk_evaluation_call_run_workspace",
        ),
        UniqueConstraint("evaluation_run_id", "call_key", name="uq_evaluation_call_key"),
        CheckConstraint(
            "status IN ('sent','settled','usage_uncertain')", name="ck_evaluation_call_status"
        ),
        CheckConstraint(
            "reserved_tokens > 0 AND (actual_tokens IS NULL OR actual_tokens >= 0)",
            name="ck_evaluation_call_tokens",
        ),
        Index("ix_evaluation_call_workspace_run", "workspace_id", "evaluation_run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    evaluation_run_id: Mapped[uuid.UUID] = mapped_column()
    call_key: Mapped[str] = mapped_column(String(100))
    request_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="sent")
    reserved_tokens: Mapped[int] = mapped_column(Integer)
    actual_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
