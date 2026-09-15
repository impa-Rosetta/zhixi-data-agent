import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, status

from apps.api.authorization import authorize
from apps.api.dependencies import CurrentUser, DbSession
from apps.api.services.analysis_conversations import (
    AnalysisConversationServiceError,
    create_conversation,
    get_conversation,
    get_conversation_view,
    list_conversations,
    send_conversation_message,
)
from packages.platform_core.policy import Action
from packages.shared_contracts.agents import (
    AnalysisConversationPage,
    AnalysisConversationResponse,
    AnalysisConversationViewResponse,
    CreateAnalysisConversationRequest,
    SendAnalysisConversationMessageRequest,
)

router = APIRouter(
    prefix="/api/v1/workspaces/{workspace_id}/analysis-conversations",
    tags=["analysis-conversations"],
)
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=100)]


def _error(exc: AnalysisConversationServiceError) -> HTTPException:
    status_code = (
        status.HTTP_404_NOT_FOUND
        if exc.code == "analysis_conversation.not_found"
        else status.HTTP_409_CONFLICT
    )
    return HTTPException(status_code, detail={"code": exc.code, "message": exc.message})


@router.get("", response_model=AnalysisConversationPage)
def index(
    workspace_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> AnalysisConversationPage:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.ANALYSIS_RUN)
    return list_conversations(db, workspace_id=workspace_id, limit=limit, offset=offset)


@router.post("", response_model=AnalysisConversationResponse, status_code=status.HTTP_201_CREATED)
def create(
    workspace_id: uuid.UUID,
    payload: CreateAnalysisConversationRequest,
    idempotency_key: IdempotencyKey,
    db: DbSession,
    user: CurrentUser,
) -> AnalysisConversationResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.ANALYSIS_RUN)
    try:
        result = create_conversation(
            db,
            workspace_id=workspace_id,
            actor_user_id=user.id,
            idempotency_key=idempotency_key,
            payload=payload,
        )
    except AnalysisConversationServiceError as exc:
        db.rollback()
        raise _error(exc) from exc
    db.commit()
    return result


@router.get("/{conversation_id}", response_model=AnalysisConversationResponse)
def detail(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> AnalysisConversationResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.ANALYSIS_RUN)
    try:
        return get_conversation(db, workspace_id=workspace_id, conversation_id=conversation_id)
    except AnalysisConversationServiceError as exc:
        raise _error(exc) from exc


@router.get("/{conversation_id}/view", response_model=AnalysisConversationViewResponse)
def view(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> AnalysisConversationViewResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.ANALYSIS_RUN)
    try:
        return get_conversation_view(
            db,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            limit=limit,
            offset=offset,
        )
    except AnalysisConversationServiceError as exc:
        raise _error(exc) from exc


@router.post("/{conversation_id}/messages", response_model=AnalysisConversationResponse)
def message(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    payload: SendAnalysisConversationMessageRequest,
    idempotency_key: IdempotencyKey,
    db: DbSession,
    user: CurrentUser,
) -> AnalysisConversationResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.ANALYSIS_RUN)
    try:
        result = send_conversation_message(
            db,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            actor_user_id=user.id,
            idempotency_key=idempotency_key,
            payload=payload,
        )
    except AnalysisConversationServiceError as exc:
        db.rollback()
        raise _error(exc) from exc
    db.commit()
    return result
