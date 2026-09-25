import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Header, HTTPException, Query, status
from fastapi.responses import Response

from apps.api.authorization import authorize
from apps.api.dependencies import CurrentUser, DbSession
from apps.api.services.analysis_reports import (
    AnalysisReportServiceError,
    create_report,
    get_report,
    list_reports,
    read_report_file,
    retry_report,
)
from packages.agent_core.persistence import AnalysisReportFormat
from packages.platform_core.policy import Action
from packages.platform_core.settings import get_settings
from packages.reporting.generation import MinioReportObjectStorage
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
    if exc.code in {
        "analysis_report.not_found",
        "analysis_report.conversation_not_found",
        "analysis_report.file_not_found",
    }:
        code = status.HTTP_404_NOT_FOUND
    elif exc.code == "analysis_report.expired":
        code = status.HTTP_410_GONE
    elif exc.code in {
        "analysis_report.storage_unavailable",
        "analysis_report.integrity_failed",
        "analysis_report.file_too_large",
    }:
        code = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        code = status.HTTP_409_CONFLICT
    return HTTPException(code, detail={"code": exc.code, "message": exc.message})


def _storage() -> MinioReportObjectStorage:
    settings = get_settings()
    return MinioReportObjectStorage(
        endpoint_url=settings.s3_endpoint_url,
        access_key=settings.s3_access_key.get_secret_value(),
        secret_key=settings.s3_secret_key.get_secret_value(),
        bucket=settings.s3_bucket,
    )


def _file_response(
    *,
    db: DbSession,
    workspace_id: uuid.UUID,
    report_id: uuid.UUID,
    user: CurrentUser,
    format_value: AnalysisReportFormat,
    preview: bool,
) -> Response:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.ANALYSIS_REPORT_DOWNLOAD)
    try:
        storage = _storage()
    except Exception as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "analysis_report.storage_unavailable",
                "message": "Report file unavailable",
            },
        ) from exc
    try:
        content, media_type, title = read_report_file(
            db,
            workspace_id=workspace_id,
            report_id=report_id,
            format_value=format_value,
            storage=storage,
            actor_user_id=user.id,
            preview=preview,
        )
    except AnalysisReportServiceError as exc:
        db.rollback()
        raise _error(exc) from exc
    extension = {"markdown": "md", "html": "html", "pdf": "pdf"}[format_value.value]
    filename = quote(f"{title[:80]}.{extension}", safe="")
    disposition = "inline" if preview else "attachment"
    headers = {
        "Content-Disposition": (
            f"{disposition}; filename=report-{report_id}.{extension}; filename*=UTF-8''{filename}"
        ),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }
    if preview:
        headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox"
        )
    return Response(content=content, media_type=media_type, headers=headers)


@router.get("/{report_id}/preview", response_class=Response)
def preview(
    workspace_id: uuid.UUID,
    report_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> Response:
    return _file_response(
        db=db,
        workspace_id=workspace_id,
        report_id=report_id,
        user=user,
        format_value=AnalysisReportFormat.HTML,
        preview=True,
    )


@router.get("/{report_id}/files/{format_value}", response_class=Response)
def download(
    workspace_id: uuid.UUID,
    report_id: uuid.UUID,
    format_value: AnalysisReportFormat,
    db: DbSession,
    user: CurrentUser,
) -> Response:
    return _file_response(
        db=db,
        workspace_id=workspace_id,
        report_id=report_id,
        user=user,
        format_value=format_value,
        preview=False,
    )


@router.get("", response_model=AnalysisReportPage)
def index(
    workspace_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    conversation_id: uuid.UUID | None = None,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> AnalysisReportPage:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.ANALYSIS_REPORT_READ)
    return list_reports(
        db,
        workspace_id=workspace_id,
        conversation_id=conversation_id,
        limit=limit,
        offset=offset,
    )


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


@router.post("/{report_id}/retry", response_model=AnalysisReportResponse)
def retry(
    workspace_id: uuid.UUID,
    report_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> AnalysisReportResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.ANALYSIS_REPORT_RETRY)
    try:
        result = retry_report(
            db,
            workspace_id=workspace_id,
            report_id=report_id,
            actor_user_id=user.id,
        )
    except AnalysisReportServiceError as exc:
        db.rollback()
        raise _error(exc) from exc
    db.commit()
    return result
