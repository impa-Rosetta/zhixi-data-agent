"""Durable SQLAlchemy models for governed Agent execution."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from packages.platform_core.database import Base


def _values(enum_type: type[enum.Enum]) -> list[str]:
    return [str(item.value) for item in enum_type]


class AnalysisRunStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_CLARIFICATION = "waiting_for_clarification"
    WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"
    COMPLETED = "completed"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AnalysisStepStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class AnalysisConversationStatus(enum.StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class AnalysisTurnRelation(enum.StrEnum):
    INITIAL = "initial"
    CONTINUE = "continue"
    REFINE = "refine"
    EXPLAIN = "explain"
    COMPARE = "compare"
    SWITCH_TOPIC = "switch_topic"


class AnalysisTurnStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_USER = "waiting_for_user"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AnalysisConversation(Base):
    __tablename__ = "analysis_conversations"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_analysis_conversation_idempotency",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_analysis_conversation_workspace_id"),
        Index(
            "ix_analysis_conversation_workspace_updated",
            "workspace_id",
            "updated_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[AnalysisConversationStatus] = mapped_column(
        Enum(AnalysisConversationStatus, native_enum=False, values_callable=_values), index=True
    )
    context: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    active_turn_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "analysis_turns.id",
            name="fk_analysis_conversation_active_turn",
            ondelete="SET NULL",
            use_alter=True,
        ),
        index=True,
    )
    last_turn_sequence: Mapped[int] = mapped_column(Integer, default=0)
    next_event_sequence: Mapped[int] = mapped_column(Integer, default=1)
    version: Mapped[int] = mapped_column(Integer, default=1)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AnalysisTurn(Base):
    __tablename__ = "analysis_turns"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence", name="uq_analysis_turn_sequence"),
        UniqueConstraint("analysis_run_id", name="uq_analysis_turn_run"),
        UniqueConstraint("workspace_id", "id", name="uq_analysis_turn_workspace_id"),
        ForeignKeyConstraint(
            ["workspace_id", "conversation_id"],
            ["analysis_conversations.workspace_id", "analysis_conversations.id"],
            name="fk_analysis_turn_conversation_workspace",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "analysis_run_id"],
            ["analysis_runs.workspace_id", "analysis_runs.id"],
            name="fk_analysis_turn_run_workspace",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        Index("ix_analysis_turn_conversation_status", "conversation_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    parent_turn_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analysis_turns.id", ondelete="SET NULL"), index=True
    )
    analysis_run_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    relation: Mapped[AnalysisTurnRelation] = mapped_column(
        Enum(AnalysisTurnRelation, native_enum=False, values_callable=_values)
    )
    status: Mapped[AnalysisTurnStatus] = mapped_column(
        Enum(AnalysisTurnStatus, native_enum=False, values_callable=_values), index=True
    )
    context_before: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    context_after: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_analysis_run_idempotency"),
        UniqueConstraint("workspace_id", "id", name="uq_analysis_run_workspace_id"),
        UniqueConstraint("turn_id", name="uq_analysis_run_turn"),
        ForeignKeyConstraint(
            ["workspace_id", "conversation_id"],
            ["analysis_conversations.workspace_id", "analysis_conversations.id"],
            name="fk_analysis_run_conversation_workspace",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "turn_id"],
            ["analysis_turns.workspace_id", "analysis_turns.id"],
            name="fk_analysis_run_turn_workspace",
            ondelete="RESTRICT",
        ),
        Index("ix_analysis_run_workspace_created", "workspace_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    turn_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    status: Mapped[AnalysisRunStatus] = mapped_column(
        Enum(AnalysisRunStatus, native_enum=False, values_callable=_values), index=True
    )
    current_node: Mapped[str] = mapped_column(String(64), default="understand")
    context: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    frozen_versions: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    budget: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    model_calls: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    replan_count: Mapped[int] = mapped_column(Integer, default=0)
    next_event_sequence: Mapped[int] = mapped_column(Integer, default=1)
    error_code: Mapped[str | None] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer, default=1)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AnalysisMessage(Base):
    __tablename__ = "analysis_messages"
    __table_args__ = (
        UniqueConstraint("run_id", "idempotency_key", name="uq_analysis_message_idempotency"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    context_patch: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalysisPlanRecord(Base):
    __tablename__ = "analysis_plans"
    __table_args__ = (UniqueConstraint("run_id", "revision", name="uq_analysis_plan_revision"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer)
    goal: Mapped[str] = mapped_column(Text)
    document: Mapped[dict[str, object]] = mapped_column(JSON)
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalysisStepRecord(Base):
    __tablename__ = "analysis_steps"
    __table_args__ = (UniqueConstraint("plan_id", "step_key", name="uq_analysis_step_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_plans.id", ondelete="CASCADE"), index=True
    )
    step_key: Mapped[str] = mapped_column(String(64))
    tool_name: Mapped[str] = mapped_column(String(64))
    arguments: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    dependencies: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[AnalysisStepStatus] = mapped_column(
        Enum(AnalysisStepStatus, native_enum=False, values_callable=_values)
    )
    error_code: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnalysisToolCall(Base):
    __tablename__ = "analysis_tool_calls"
    __table_args__ = (
        UniqueConstraint("run_id", "idempotency_key", name="uq_analysis_tool_call_idempotency"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True
    )
    step_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_steps.id", ondelete="CASCADE"), index=True
    )
    tool_name: Mapped[str] = mapped_column(String(64))
    tool_version: Mapped[str] = mapped_column(String(32))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    argument_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[AnalysisStepStatus] = mapped_column(
        Enum(AnalysisStepStatus, native_enum=False, values_callable=_values)
    )
    result_summary: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalysisArtifact(Base):
    __tablename__ = "analysis_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True
    )
    artifact_type: Mapped[str] = mapped_column(String(50), index=True)
    summary: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    object_key: Mapped[str | None] = mapped_column(String(500))
    content_digest: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalysisEvidence(Base):
    __tablename__ = "analysis_evidence"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True
    )
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analysis_artifacts.id", ondelete="SET NULL"), index=True
    )
    evidence_type: Mapped[str] = mapped_column(String(50), index=True)
    reference: Mapped[dict[str, object]] = mapped_column(JSON)
    evidence_digest: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalysisValidation(Base):
    __tablename__ = "analysis_validations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True
    )
    validation_type: Mapped[str] = mapped_column(String(50))
    outcome: Mapped[str] = mapped_column(String(20))
    findings: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalysisCheckpoint(Base):
    __tablename__ = "analysis_checkpoints"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_analysis_checkpoint_sequence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    node: Mapped[str] = mapped_column(String(64))
    graph_version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    state: Mapped[dict[str, object]] = mapped_column(JSON)
    restricted_reasoning: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalysisEvent(Base):
    __tablename__ = "analysis_events"
    __table_args__ = (UniqueConstraint("run_id", "sequence", name="uq_analysis_event_sequence"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalysisConversationEvent(Base):
    """A replayable, conversation-scoped projection of turn and run events."""

    __tablename__ = "analysis_conversation_events"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_analysis_conversation_event_sequence",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "conversation_id"],
            ["analysis_conversations.workspace_id", "analysis_conversations.id"],
            name="fk_analysis_conversation_event_conversation_workspace",
            ondelete="CASCADE",
        ),
        Index(
            "ix_analysis_conversation_event_replay",
            "conversation_id",
            "sequence",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(index=True)
    turn_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analysis_turns.id", ondelete="SET NULL"), index=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="SET NULL"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    run_event_sequence: Mapped[int | None] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
