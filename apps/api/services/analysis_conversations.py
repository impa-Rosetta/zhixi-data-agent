"""Transactional domain services for durable multi-turn analysis conversations."""

import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.audit import add_audit_event
from apps.api.services.analysis_runs import append_message, cancel_run, create_run, get_run_view
from packages.agent_core.persistence import (
    AnalysisArtifact,
    AnalysisConversation,
    AnalysisConversationStatus,
    AnalysisMessage,
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisTurn,
    AnalysisTurnRelation,
    AnalysisTurnStatus,
)
from packages.agent_core.recommendations import recommend_follow_ups
from packages.shared_contracts.agents import (
    AnalysisConversationContext,
    AnalysisConversationPage,
    AnalysisConversationResponse,
    AnalysisConversationSummaryResponse,
    AnalysisConversationTurnViewResponse,
    AnalysisConversationViewResponse,
    AnalysisTurnResponse,
    CreateAnalysisConversationRequest,
    SendAnalysisConversationMessageRequest,
)


class AnalysisConversationServiceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def _title(message: str) -> str:
    normalized = re.sub(r"\s+", " ", message).strip()
    return normalized if len(normalized) <= 60 else f"{normalized[:57]}..."


def _context(value: dict[str, object]) -> AnalysisConversationContext:
    return AnalysisConversationContext.model_validate(value)


def _response(conversation: AnalysisConversation) -> AnalysisConversationResponse:
    return AnalysisConversationResponse(
        id=conversation.id,
        workspace_id=conversation.workspace_id,
        title=conversation.title,
        status=conversation.status.value,
        context=_context(dict(conversation.context)),
        active_turn_id=conversation.active_turn_id,
        last_turn_sequence=conversation.last_turn_sequence,
        last_event_sequence=max(0, conversation.next_event_sequence - 1),
        version=conversation.version,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        archived_at=conversation.archived_at,
    )


def _get_conversation(
    db: Session,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
) -> AnalysisConversation:
    conversation = db.scalar(
        select(AnalysisConversation).where(
            AnalysisConversation.id == conversation_id,
            AnalysisConversation.workspace_id == workspace_id,
        )
    )
    if conversation is None:
        raise AnalysisConversationServiceError(
            "analysis_conversation.not_found", "Analysis conversation not found"
        )
    return conversation


def create_conversation(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    idempotency_key: str,
    payload: CreateAnalysisConversationRequest,
) -> AnalysisConversationResponse:
    existing = db.scalar(
        select(AnalysisConversation).where(
            AnalysisConversation.workspace_id == workspace_id,
            AnalysisConversation.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return _response(existing)

    title = _title(payload.message)
    context = AnalysisConversationContext(topic_summary=title)
    conversation = AnalysisConversation(
        workspace_id=workspace_id,
        created_by_user_id=actor_user_id,
        idempotency_key=idempotency_key,
        title=title,
        status=AnalysisConversationStatus.ACTIVE,
        context=context.model_dump(mode="json"),
        last_turn_sequence=1,
    )
    db.add(conversation)
    db.flush()
    turn = AnalysisTurn(
        workspace_id=workspace_id,
        conversation_id=conversation.id,
        sequence=1,
        relation=AnalysisTurnRelation.INITIAL,
        status=AnalysisTurnStatus.QUEUED,
        context_before=AnalysisConversationContext().model_dump(mode="json"),
        context_after=context.model_dump(mode="json"),
    )
    db.add(turn)
    db.flush()
    run_key = f"conversation:{conversation.id}:turn:1"
    run_response = create_run(
        db,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        idempotency_key=run_key,
        payload=payload,
        conversation_id=conversation.id,
        turn_id=turn.id,
    )
    turn.analysis_run_id = run_response.id
    conversation.active_turn_id = turn.id
    add_audit_event(
        db,
        action="analysis_conversation.created",
        outcome="success",
        resource_type="analysis_conversation",
        resource_id=str(conversation.id),
        actor_user_id=actor_user_id,
        workspace_id=workspace_id,
    )
    db.flush()
    return _response(conversation)


def get_conversation(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
) -> AnalysisConversationResponse:
    return _response(_get_conversation(db, workspace_id, conversation_id))


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


def _turn_response(turn: AnalysisTurn, run: AnalysisRun) -> AnalysisTurnResponse:
    return AnalysisTurnResponse(
        id=turn.id,
        sequence=turn.sequence,
        parent_turn_id=turn.parent_turn_id,
        analysis_run_id=run.id,
        relation=turn.relation.value,
        status=_turn_status(run.status).value,
        queued_at=turn.queued_at,
        started_at=run.started_at or turn.started_at,
        finished_at=run.finished_at or turn.finished_at,
        created_at=turn.created_at,
        updated_at=max(turn.updated_at, run.updated_at),
    )


def get_conversation_view(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    limit: int = 20,
    offset: int = 0,
) -> AnalysisConversationViewResponse:
    conversation = _get_conversation(db, workspace_id, conversation_id)
    bounded_limit = max(1, min(limit, 100))
    bounded_offset = max(0, offset)
    total = db.scalar(
        select(func.count())
        .select_from(AnalysisTurn)
        .where(
            AnalysisTurn.workspace_id == workspace_id,
            AnalysisTurn.conversation_id == conversation.id,
        )
    )
    rows = list(
        db.execute(
            select(AnalysisTurn, AnalysisRun)
            .join(AnalysisRun, AnalysisRun.id == AnalysisTurn.analysis_run_id)
            .where(
                AnalysisTurn.workspace_id == workspace_id,
                AnalysisTurn.conversation_id == conversation.id,
                AnalysisRun.workspace_id == workspace_id,
            )
            .order_by(AnalysisTurn.sequence.desc())
            .offset(bounded_offset)
            .limit(bounded_limit)
        ).all()
    )
    rows.reverse()
    return AnalysisConversationViewResponse(
        conversation=_response(conversation),
        turns=[
            AnalysisConversationTurnViewResponse(
                turn=_turn_response(turn, run),
                analysis=get_run_view(db, workspace_id=workspace_id, run_id=run.id),
                suggested_follow_ups=recommend_follow_ups(
                    context=_context(dict(turn.context_after)),
                    run_status=run.status,
                    artifacts=list(
                        db.scalars(
                            select(AnalysisArtifact).where(
                                AnalysisArtifact.workspace_id == workspace_id,
                                AnalysisArtifact.run_id == run.id,
                            )
                        )
                    ),
                ),
            )
            for turn, run in rows
        ],
        total_turns=int(total or 0),
        limit=bounded_limit,
        offset=bounded_offset,
    )


def send_conversation_message(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    idempotency_key: str,
    payload: SendAnalysisConversationMessageRequest,
) -> AnalysisConversationResponse:
    conversation = _get_conversation(db, workspace_id, conversation_id)
    if conversation.status is AnalysisConversationStatus.ARCHIVED:
        raise AnalysisConversationServiceError(
            "analysis_conversation.archived", "Archived conversation is read-only"
        )
    existing_message = db.scalar(
        select(AnalysisMessage.id)
        .join(AnalysisRun, AnalysisRun.id == AnalysisMessage.run_id)
        .where(
            AnalysisRun.conversation_id == conversation.id,
            AnalysisMessage.idempotency_key == idempotency_key,
            AnalysisMessage.workspace_id == workspace_id,
        )
    )
    if existing_message is not None:
        return _response(conversation)

    active_turn = (
        db.get(AnalysisTurn, conversation.active_turn_id)
        if conversation.active_turn_id is not None
        else None
    )
    active_run = (
        db.get(AnalysisRun, active_turn.analysis_run_id)
        if active_turn is not None and active_turn.analysis_run_id is not None
        else None
    )
    if active_run is not None and active_run.status in {
        AnalysisRunStatus.WAITING_FOR_CLARIFICATION,
        AnalysisRunStatus.WAITING_FOR_CONFIRMATION,
        AnalysisRunStatus.FAILED_RETRYABLE,
    }:
        if active_turn is None:
            raise AnalysisConversationServiceError(
                "analysis_conversation.state_invalid", "Active run has no turn"
            )
        append_message(
            db,
            workspace_id=workspace_id,
            run_id=active_run.id,
            actor_user_id=actor_user_id,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        active_turn.status = AnalysisTurnStatus.RUNNING
        conversation.version += 1
        db.flush()
        return _response(conversation)

    sequence = conversation.last_turn_sequence + 1
    parent_turn = db.scalar(
        select(AnalysisTurn)
        .where(
            AnalysisTurn.conversation_id == conversation.id,
            AnalysisTurn.workspace_id == workspace_id,
        )
        .order_by(AnalysisTurn.sequence.desc())
        .limit(1)
    )
    context_before = _context(dict(conversation.context))
    context_after = context_before.model_copy(update={"last_relation": "continue"})
    turn = AnalysisTurn(
        workspace_id=workspace_id,
        conversation_id=conversation.id,
        sequence=sequence,
        parent_turn_id=parent_turn.id if parent_turn is not None else None,
        relation=AnalysisTurnRelation.CONTINUE,
        status=AnalysisTurnStatus.QUEUED,
        context_before=context_before.model_dump(mode="json"),
        context_after=context_after.model_dump(mode="json"),
    )
    db.add(turn)
    db.flush()
    has_active_run = active_run is not None and active_run.status in {
        AnalysisRunStatus.QUEUED,
        AnalysisRunStatus.RUNNING,
    }
    run_response = create_run(
        db,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        idempotency_key=f"conversation:{conversation.id}:turn:{sequence}",
        payload=CreateAnalysisConversationRequest(message=payload.message),
        conversation_id=conversation.id,
        turn_id=turn.id,
        initial_message_idempotency_key=idempotency_key,
        enqueue=not has_active_run,
    )
    turn.analysis_run_id = run_response.id
    if payload.suggestion_id is not None:
        suggested_run = db.get(AnalysisRun, run_response.id)
        if suggested_run is not None:
            suggested_run.context = {
                **suggested_run.context,
                "suggestion_id": payload.suggestion_id,
            }
    conversation.context = context_after.model_dump(mode="json")
    conversation.last_turn_sequence = sequence
    conversation.version += 1
    if not has_active_run:
        conversation.active_turn_id = turn.id
    add_audit_event(
        db,
        action="analysis_conversation.message_added",
        outcome="success",
        resource_type="analysis_conversation",
        resource_id=str(conversation.id),
        actor_user_id=actor_user_id,
        workspace_id=workspace_id,
    )
    if payload.suggestion_id is not None:
        add_audit_event(
            db,
            action="analysis_conversation.suggestion_clicked",
            outcome="success",
            resource_type="analysis_conversation",
            resource_id=str(conversation.id),
            actor_user_id=actor_user_id,
            workspace_id=workspace_id,
            detail=f"suggestion_id={payload.suggestion_id};turn_sequence={sequence}",
        )
    db.flush()
    return _response(conversation)


def cancel_conversation_turn(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    turn_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> AnalysisConversationResponse:
    conversation = _get_conversation(db, workspace_id, conversation_id)
    if conversation.active_turn_id != turn_id:
        raise AnalysisConversationServiceError(
            "analysis_conversation.turn_not_active",
            "Only the active conversation turn can be cancelled",
        )
    turn = db.scalar(
        select(AnalysisTurn).where(
            AnalysisTurn.id == turn_id,
            AnalysisTurn.workspace_id == workspace_id,
            AnalysisTurn.conversation_id == conversation_id,
        )
    )
    if turn is None or turn.analysis_run_id is None:
        raise AnalysisConversationServiceError(
            "analysis_conversation.turn_not_found", "Analysis turn not found"
        )
    cancel_run(
        db,
        workspace_id=workspace_id,
        run_id=turn.analysis_run_id,
        actor_user_id=actor_user_id,
    )
    db.flush()
    return _response(conversation)


def _summary(
    conversation: AnalysisConversation,
    active_status: AnalysisTurnStatus | None,
    last_message: str | None,
) -> AnalysisConversationSummaryResponse:
    preview = None
    if last_message is not None:
        normalized = re.sub(r"\s+", " ", last_message).strip()
        preview = normalized if len(normalized) <= 300 else f"{normalized[:297]}..."
    return AnalysisConversationSummaryResponse(
        id=conversation.id,
        title=conversation.title,
        status=conversation.status.value,
        active_turn_id=conversation.active_turn_id,
        active_turn_status=active_status.value if active_status is not None else None,
        last_turn_sequence=conversation.last_turn_sequence,
        last_message_preview=preview,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def list_conversations(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    limit: int = 30,
    offset: int = 0,
) -> AnalysisConversationPage:
    bounded_limit = max(1, min(limit, 100))
    bounded_offset = max(0, offset)
    total = db.scalar(
        select(func.count())
        .select_from(AnalysisConversation)
        .where(AnalysisConversation.workspace_id == workspace_id)
    )
    active_status = (
        select(AnalysisTurn.status)
        .where(
            AnalysisTurn.id == AnalysisConversation.active_turn_id,
            AnalysisTurn.workspace_id == AnalysisConversation.workspace_id,
        )
        .correlate(AnalysisConversation)
        .scalar_subquery()
    )
    last_message = (
        select(AnalysisMessage.content)
        .join(AnalysisRun, AnalysisRun.id == AnalysisMessage.run_id)
        .where(
            AnalysisRun.conversation_id == AnalysisConversation.id,
            AnalysisMessage.workspace_id == AnalysisConversation.workspace_id,
        )
        .order_by(AnalysisMessage.created_at.desc(), AnalysisMessage.id.desc())
        .limit(1)
        .correlate(AnalysisConversation)
        .scalar_subquery()
    )
    rows = db.execute(
        select(
            AnalysisConversation,
            active_status.label("active_turn_status"),
            last_message.label("last_message"),
        )
        .where(AnalysisConversation.workspace_id == workspace_id)
        .order_by(AnalysisConversation.updated_at.desc(), AnalysisConversation.id.desc())
        .offset(bounded_offset)
        .limit(bounded_limit)
    ).all()
    return AnalysisConversationPage(
        items=[
            _summary(conversation, turn_status, message)
            for conversation, turn_status, message in rows
        ],
        total=int(total or 0),
        limit=bounded_limit,
        offset=bounded_offset,
    )
