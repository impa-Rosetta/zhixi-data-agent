"""Conversation lifecycle synchronization around immutable analysis runs."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.agent_core.persistence import (
    AnalysisConversation,
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisTurn,
    AnalysisTurnStatus,
)
from packages.platform_core.models import OutboxEvent


def _turn_status(run_status: AnalysisRunStatus) -> AnalysisTurnStatus:
    if run_status is AnalysisRunStatus.QUEUED:
        return AnalysisTurnStatus.QUEUED
    if run_status is AnalysisRunStatus.RUNNING:
        return AnalysisTurnStatus.RUNNING
    if run_status in {
        AnalysisRunStatus.WAITING_FOR_CLARIFICATION,
        AnalysisRunStatus.WAITING_FOR_CONFIRMATION,
        AnalysisRunStatus.FAILED_RETRYABLE,
    }:
        return AnalysisTurnStatus.WAITING_FOR_USER
    if run_status is AnalysisRunStatus.COMPLETED:
        return AnalysisTurnStatus.COMPLETED
    if run_status is AnalysisRunStatus.CANCELLED:
        return AnalysisTurnStatus.CANCELLED
    return AnalysisTurnStatus.FAILED


def synchronize_conversation_after_run(db: Session, *, run_id: uuid.UUID) -> bool:
    """Project a run state and activate at most one queued successor."""
    run = db.get(AnalysisRun, run_id)
    if run is None or run.conversation_id is None or run.turn_id is None:
        return False
    conversation = db.scalar(
        select(AnalysisConversation)
        .where(
            AnalysisConversation.id == run.conversation_id,
            AnalysisConversation.workspace_id == run.workspace_id,
        )
        .with_for_update()
    )
    turn = db.scalar(
        select(AnalysisTurn).where(
            AnalysisTurn.id == run.turn_id,
            AnalysisTurn.workspace_id == run.workspace_id,
            AnalysisTurn.conversation_id == run.conversation_id,
        )
    )
    if conversation is None or turn is None:
        return False

    desired_status = _turn_status(run.status)
    changed = turn.status is not desired_status
    turn.status = desired_status
    turn.started_at = run.started_at or turn.started_at
    turn.finished_at = run.finished_at or turn.finished_at
    if desired_status in {
        AnalysisTurnStatus.QUEUED,
        AnalysisTurnStatus.RUNNING,
        AnalysisTurnStatus.WAITING_FOR_USER,
    }:
        if conversation.active_turn_id != turn.id:
            conversation.active_turn_id = turn.id
            changed = True
    elif conversation.active_turn_id == turn.id:
        next_row = db.execute(
            select(AnalysisTurn, AnalysisRun)
            .join(AnalysisRun, AnalysisRun.id == AnalysisTurn.analysis_run_id)
            .where(
                AnalysisTurn.workspace_id == run.workspace_id,
                AnalysisTurn.conversation_id == conversation.id,
                AnalysisTurn.sequence > turn.sequence,
                AnalysisTurn.status == AnalysisTurnStatus.QUEUED,
                AnalysisRun.status == AnalysisRunStatus.QUEUED,
            )
            .order_by(AnalysisTurn.sequence)
            .limit(1)
        ).one_or_none()
        conversation.active_turn_id = next_row[0].id if next_row is not None else None
        changed = True
        if next_row is not None:
            next_run = next_row[1]
            existing_outbox = db.scalar(
                select(OutboxEvent.id).where(
                    OutboxEvent.aggregate_id == next_run.id,
                    OutboxEvent.event_type == "analysis.run.requested",
                )
            )
            if existing_outbox is None:
                db.add(
                    OutboxEvent(
                        aggregate_type="analysis_run",
                        aggregate_id=next_run.id,
                        event_type="analysis.run.requested",
                        payload={"run_id": str(next_run.id)},
                    )
                )
    if changed:
        conversation.version += 1
        conversation.updated_at = datetime.now(UTC)
    db.flush()
    return changed
