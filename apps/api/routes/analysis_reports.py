import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, status

from apps.api.authorization import authorize
from apps.api.dependencies import CurrentUser, DbSession
from apps.api.services.analysis_reports import (
    AnalysisReportServiceError,
    create_report,
    get_report,
    list_reports,
)
from packages.platform_core.policy import Action
from packages.shared_contracts.reports import (
    AnalysisReportPage,
    AnalysisReportResponse,
    CreateAnalysisReportRequest,
)

router = APIRouter(
    prefix="/api/v1/workspaces/{workspace_id}/reports",
    tags=["analysis-reports"],
)
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=100)]


def _error(exc: AnalysisReportServiceError) -> HTTPException:
    if exc.code in {"analysis_report.not_found", "analysis_report.conversation_not_found"}:
        code = status.HTTP_404_NOT_FOUND
    else:
        code = status.HTTP_409_CONFLICT
    return HTTPException(code, detail={"code": exc.code, "message": exc.message})


@router.get("", response_model=AnalysisReportPage)
def index(
    workspace_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> AnalysisReportPage:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.ANALYSIS_REPORT_READ)
    return list_reports(db, workspace_id=workspace_id, limit=limit, offset=offset)


@router.post("", response_model=AnalysisReportResponse, status_code=status.HTTP_201_CREATED)
def create(
    workspace_id: uuid.UUID,
    payload: CreateAnalysisReportRequest,
    idempotency_key: IdempotencyKey,
    db: DbSession,
    user: CurrentUser,
) -> AnalysisReportResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.ANALYSIS_REPORT_CREATE)
    try:
        result = create_report(
            db,
            workspace_id=workspace_id,
            actor_user_id=user.id,
            idempotency_key=idempotency_key,
            payload=payload,
        )
    except AnalysisReportServiceError as exc:
        db.rollback()
        raise _error(exc) from exc
    db.commit()
    return result


@router.get("/{report_id}", response_model=AnalysisReportResponse)
def detail(
    workspace_id: uuid.UUID,
    report_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> AnalysisReportResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.ANALYSIS_REPORT_READ)
    try:
        return get_report(db, workspace_id=workspace_id, report_id=report_id)
    except AnalysisReportServiceError as exc:
        raise _error(exc) from exc
