"""Transactional domain services for durable multi-turn analysis conversations."""

import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.audit import add_audit_event
from apps.api.services.analysis_runs import create_run
from packages.agent_core.persistence import (
    AnalysisConversation,
    AnalysisConversationStatus,
    AnalysisMessage,
    AnalysisRun,
    AnalysisTurn,
    AnalysisTurnRelation,
    AnalysisTurnStatus,
)
from packages.shared_contracts.agents import (
    AnalysisConversationContext,
    AnalysisConversationPage,
    AnalysisConversationResponse,
    AnalysisConversationSummaryResponse,
    CreateAnalysisConversationRequest,
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
        select(func.count()).select_from(AnalysisConversation).where(
            AnalysisConversation.workspace_id == workspace_id
        )
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
