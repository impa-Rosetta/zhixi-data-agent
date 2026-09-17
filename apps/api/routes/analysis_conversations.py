import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from apps.api.authorization import authorize
from apps.api.dependencies import CurrentUser, DbSession
from apps.api.services.analysis_conversations import (
    AnalysisConversationServiceError,
    cancel_conversation_turn,
    create_conversation,
    get_conversation,
    get_conversation_view,
    list_conversations,
    send_conversation_message,
)
from packages.agent_core.conversation_events import stream_conversation_events
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


@router.post(
    "/{conversation_id}/turns/{turn_id}/cancel",
    response_model=AnalysisConversationResponse,
)
def cancel_turn(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    turn_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> AnalysisConversationResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.ANALYSIS_RUN)
    try:
        result = cancel_conversation_turn(
            db,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            turn_id=turn_id,
            actor_user_id=user.id,
        )
    except AnalysisConversationServiceError as exc:
        db.rollback()
        raise _error(exc) from exc
    db.commit()
    return result


@router.get("/{conversation_id}/events/stream", response_class=StreamingResponse)
def event_stream(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    request: Request,
    db: DbSession,
    user: CurrentUser,
    after: int = Query(default=0, ge=0),
) -> StreamingResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.ANALYSIS_RUN)
    try:
        get_conversation(db, workspace_id=workspace_id, conversation_id=conversation_id)
    except AnalysisConversationServiceError as exc:
        raise _error(exc) from exc
    last_event_id = request.headers.get("Last-Event-ID")
    cursor = after
    if last_event_id:
        try:
            cursor = max(cursor, int(last_event_id))
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail={"code": "analysis_conversation.invalid_event_cursor"},
            ) from exc
    return StreamingResponse(
        stream_conversation_events(
            db,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            after=cursor,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
