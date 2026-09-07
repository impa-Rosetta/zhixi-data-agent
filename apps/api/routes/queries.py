import uuid

from fastapi import APIRouter, HTTPException, status

from apps.api.authorization import authorize
from apps.api.dependencies import CurrentUser, DbSession
from apps.api.services.queries import (
    QueryServiceError,
    compile_query,
    execute_query,
    list_executions,
    validate_exploratory_query,
)
from packages.platform_core.policy import Action
from packages.shared_contracts.queries import (
    ExploratoryQueryRequest,
    QueryExecutionResponse,
    SemanticQueryRequest,
    ValidatedQueryResponse,
)

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/queries", tags=["queries"])


def _error(exc: QueryServiceError) -> HTTPException:
    if exc.code == "query.not_found":
        code = status.HTTP_404_NOT_FOUND
    elif exc.code in {"query.validation_expired", "query.snapshot_changed", "query.snapshot_stale"}:
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(code, detail={"code": exc.code, "message": exc.message})


@router.post("/compile", response_model=ValidatedQueryResponse, status_code=status.HTTP_201_CREATED)
def compile_semantic(
    workspace_id: uuid.UUID, payload: SemanticQueryRequest, db: DbSession, user: CurrentUser
) -> ValidatedQueryResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.ANALYSIS_RUN)
    try:
        result = compile_query(
            db, workspace_id=workspace_id, actor_user_id=user.id, payload=payload
        )
    except QueryServiceError as exc:
        db.rollback()
        raise _error(exc) from exc
    db.commit()
    return result


@router.post(
    "/validate-exploratory",
    response_model=ValidatedQueryResponse,
    status_code=status.HTTP_201_CREATED,
)
def validate_exploratory(
    workspace_id: uuid.UUID, payload: ExploratoryQueryRequest, db: DbSession, user: CurrentUser
) -> ValidatedQueryResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.ANALYSIS_RUN)
    try:
        result = validate_exploratory_query(
            db, workspace_id=workspace_id, actor_user_id=user.id, payload=payload
        )
    except QueryServiceError as exc:
        db.rollback()
        raise _error(exc) from exc
    db.commit()
    return result


@router.post("/{validated_query_id}/execute", response_model=QueryExecutionResponse)
def execute_validated(
    workspace_id: uuid.UUID, validated_query_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> QueryExecutionResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.ANALYSIS_RUN)
    try:
        result = execute_query(
            db,
            workspace_id=workspace_id,
            actor_user_id=user.id,
            validated_query_id=validated_query_id,
        )
    except QueryServiceError as exc:
        db.rollback()
        raise _error(exc) from exc
    db.commit()
    return result


@router.get("/executions", response_model=list[QueryExecutionResponse])
def history(
    workspace_id: uuid.UUID, db: DbSession, user: CurrentUser, limit: int = 50
) -> list[QueryExecutionResponse]:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.SEMANTIC_READ)
    return list_executions(db, workspace_id=workspace_id, limit=max(1, min(limit, 100)))
