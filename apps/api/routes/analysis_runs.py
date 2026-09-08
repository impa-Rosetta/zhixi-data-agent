import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, status

from apps.api.authorization import authorize
from apps.api.dependencies import CurrentUser, DbSession
from apps.api.services.analysis_runs import (
    AnalysisRunServiceError,
    append_message,
    cancel_run,
    confirm_run,
    create_run,
    get_run,
    get_run_view,
    list_events,
    list_runs,
    retry_run,
)
from packages.platform_core.policy import Action
from packages.shared_contracts.agents import (
    AnalysisEventResponse,
    AnalysisRunPage,
    AnalysisRunResponse,
    AnalysisRunViewResponse,
    AppendAnalysisMessageRequest,
    ConfirmAnalysisRunRequest,
    CreateAnalysisRunRequest,
)

router = APIRouter(
    prefix="/api/v1/workspaces/{workspace_id}/analysis-runs",
    tags=["analysis-runs"],
)
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=100)]


def _error(exc: AnalysisRunServiceError) -> HTTPException:
    code = status.HTTP_404_NOT_FOUND if exc.code == "analysis_run.not_found" else 409
    return HTTPException(code, detail={"code": exc.code, "message": exc.message})


@router.get("", response_model=AnalysisRunPage)
def list_analysis_runs(
    workspace_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> AnalysisRunPage:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.ANALYSIS_RUN)
    return list_runs(db, workspace_id=workspace_id, limit=limit, offset=offset)


@router.post("", response_model=AnalysisRunResponse, status_code=status.HTTP_201_CREATED)
def create(
    workspace_id: uuid.UUID,
    payload: CreateAnalysisRunRequest,
    idempotency_key: IdempotencyKey,
    db: DbSession,
    user: CurrentUser,
) -> AnalysisRunResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.ANALYSIS_RUN)
    result = create_run(
        db,
        workspace_id=workspace_id,
        actor_user_id=user.id,
        idempotency_key=idempotency_key,
        payload=payload,
    )
    db.commit()
    return result


@router.get("/{run_id}", response_model=AnalysisRunResponse)
def detail(
    workspace_id: uuid.UUID, run_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> AnalysisRunResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.ANALYSIS_RUN)
    try:
        return get_run(db, workspace_id=workspace_id, run_id=run_id)
    except AnalysisRunServiceError as exc:
        raise _error(exc) from exc


@router.get("/{run_id}/view", response_model=AnalysisRunViewResponse)
def view(
    workspace_id: uuid.UUID, run_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> AnalysisRunViewResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.ANALYSIS_RUN)
    try:
        return get_run_view(db, workspace_id=workspace_id, run_id=run_id)
    except AnalysisRunServiceError as exc:
        raise _error(exc) from exc


@router.get("/{run_id}/events", response_model=list[AnalysisEventResponse])
def events(
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    after: int = Query(default=0, ge=0),
) -> list[AnalysisEventResponse]:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.ANALYSIS_RUN)
    try:
        return list_events(db, workspace_id=workspace_id, run_id=run_id, after=after)
    except AnalysisRunServiceError as exc:
        raise _error(exc) from exc


@router.post("/{run_id}/cancel", response_model=AnalysisRunResponse)
def cancel(
    workspace_id: uuid.UUID, run_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> AnalysisRunResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.ANALYSIS_RUN)
    try:
        result = cancel_run(db, workspace_id=workspace_id, run_id=run_id, actor_user_id=user.id)
    except AnalysisRunServiceError as exc:
        db.rollback()
        raise _error(exc) from exc
    db.commit()
    return result


@router.post("/{run_id}/messages", response_model=AnalysisRunResponse)
def message(
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    payload: AppendAnalysisMessageRequest,
    idempotency_key: IdempotencyKey,
    db: DbSession,
    user: CurrentUser,
) -> AnalysisRunResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.ANALYSIS_RUN)
    try:
        result = append_message(
            db,
            workspace_id=workspace_id,
            run_id=run_id,
            actor_user_id=user.id,
            idempotency_key=idempotency_key,
            payload=payload,
        )
    except AnalysisRunServiceError as exc:
        db.rollback()
        raise _error(exc) from exc
    db.commit()
    return result


@router.post("/{run_id}/retry", response_model=AnalysisRunResponse)
def retry(
    workspace_id: uuid.UUID, run_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> AnalysisRunResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.ANALYSIS_RUN)
    try:
        result = retry_run(db, workspace_id=workspace_id, run_id=run_id, actor_user_id=user.id)
    except AnalysisRunServiceError as exc:
        db.rollback()
        raise _error(exc) from exc
    db.commit()
    return result


@router.post("/{run_id}/confirm", response_model=AnalysisRunResponse)
def confirm(
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    payload: ConfirmAnalysisRunRequest,
    db: DbSession,
    user: CurrentUser,
) -> AnalysisRunResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.ANALYSIS_RUN)
    try:
        result = confirm_run(
            db,
            workspace_id=workspace_id,
            run_id=run_id,
            actor_user_id=user.id,
            payload=payload,
        )
    except AnalysisRunServiceError as exc:
        db.rollback()
        raise _error(exc) from exc
    db.commit()
    return result
