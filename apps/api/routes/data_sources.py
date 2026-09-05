import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from apps.api.authorization import authorize
from apps.api.dependencies import CurrentUser, DbSession
from apps.api.services.data_sources import (
    DataSourceServiceError,
    change_data_source_state,
    create_data_source,
    enqueue_connection_test,
    get_data_source,
    list_data_sources,
    update_data_source,
)
from packages.platform_core.models import ScanJob, ScanJobTrigger
from packages.platform_core.policy import Action
from packages.platform_core.settings import get_settings
from packages.shared_contracts.data_sources import (
    DataSourceCreateRequest,
    DataSourceCreateResponse,
    DataSourcePage,
    DataSourceResponse,
    DataSourceUpdateRequest,
    ScanJobResponse,
    VersionRequest,
)

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}", tags=["data-sources"])


def _error(exc: DataSourceServiceError, status_code: int) -> HTTPException:
    return HTTPException(status_code, detail={"code": exc.code, "message": exc.message})


def _service_status(exc: DataSourceServiceError, default: int) -> int:
    if exc.code == "data_source.not_found":
        return status.HTTP_404_NOT_FOUND
    if exc.code in {
        "data_source.version_conflict",
        "data_source.invalid_state",
        "data_source.inactive",
        "data_source.test_in_progress",
    }:
        return status.HTTP_409_CONFLICT
    return default


def _commit(db: DbSession) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "data_source.conflict",
                "message": "A data source with the same name or active job already exists",
            },
        ) from exc


@router.post(
    "/data-sources",
    response_model=DataSourceCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create(
    workspace_id: uuid.UUID,
    payload: DataSourceCreateRequest,
    db: DbSession,
    user: CurrentUser,
) -> DataSourceCreateResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.DATA_SOURCE_MANAGE)
    try:
        source, job = create_data_source(
            db,
            workspace_id=workspace_id,
            actor_user_id=user.id,
            payload=payload,
            settings=get_settings(),
        )
    except DataSourceServiceError as exc:
        db.rollback()
        raise _error(exc, status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
    _commit(db)
    db.refresh(source)
    db.refresh(job)
    return DataSourceCreateResponse(
        data_source=DataSourceResponse.model_validate(source),
        job=ScanJobResponse.model_validate(job),
    )


@router.get("/data-sources", response_model=DataSourcePage)
def list_sources(
    workspace_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DataSourcePage:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.DATA_SOURCE_MANAGE)
    items, total = list_data_sources(db, workspace_id=workspace_id, limit=limit, offset=offset)
    return DataSourcePage(
        items=[DataSourceResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/data-sources/{data_source_id}", response_model=DataSourceResponse)
def detail(
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> DataSourceResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.DATA_SOURCE_MANAGE)
    try:
        return DataSourceResponse.model_validate(
            get_data_source(db, workspace_id=workspace_id, data_source_id=data_source_id)
        )
    except DataSourceServiceError as exc:
        raise _error(exc, status.HTTP_404_NOT_FOUND) from exc


@router.patch("/data-sources/{data_source_id}", response_model=DataSourceResponse)
def update(
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    payload: DataSourceUpdateRequest,
    db: DbSession,
    user: CurrentUser,
) -> DataSourceResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.DATA_SOURCE_MANAGE)
    try:
        source, _ = update_data_source(
            db,
            workspace_id=workspace_id,
            data_source_id=data_source_id,
            actor_user_id=user.id,
            payload=payload,
            settings=get_settings(),
        )
    except DataSourceServiceError as exc:
        db.rollback()
        code = _service_status(exc, status.HTTP_422_UNPROCESSABLE_CONTENT)
        raise _error(exc, code) from exc
    _commit(db)
    db.refresh(source)
    return DataSourceResponse.model_validate(source)


@router.post(
    "/data-sources/{data_source_id}/test",
    response_model=ScanJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def test_connection(
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ScanJobResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.DATA_SOURCE_MANAGE)
    if idempotency_key is not None and not 1 <= len(idempotency_key) <= 200:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "request.invalid_idempotency_key", "message": "Invalid key length"},
        )
    try:
        source = get_data_source(db, workspace_id=workspace_id, data_source_id=data_source_id)
        job = enqueue_connection_test(
            db,
            source=source,
            actor_user_id=user.id,
            trigger=ScanJobTrigger.MANUAL,
            idempotency_token=idempotency_key,
        )
    except DataSourceServiceError as exc:
        db.rollback()
        raise _error(exc, _service_status(exc, status.HTTP_409_CONFLICT)) from exc
    _commit(db)
    db.refresh(job)
    return ScanJobResponse.model_validate(job)


def _state_change(
    *,
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    payload: VersionRequest,
    db: DbSession,
    user: CurrentUser,
    action: str,
) -> DataSourceResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.DATA_SOURCE_MANAGE)
    try:
        source, _ = change_data_source_state(
            db,
            workspace_id=workspace_id,
            data_source_id=data_source_id,
            actor_user_id=user.id,
            version=payload.version,
            action=action,
        )
    except DataSourceServiceError as exc:
        db.rollback()
        raise _error(exc, _service_status(exc, status.HTTP_409_CONFLICT)) from exc
    _commit(db)
    db.refresh(source)
    return DataSourceResponse.model_validate(source)


@router.post("/data-sources/{data_source_id}/disable", response_model=DataSourceResponse)
def disable(
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    payload: VersionRequest,
    db: DbSession,
    user: CurrentUser,
) -> DataSourceResponse:
    return _state_change(
        workspace_id=workspace_id,
        data_source_id=data_source_id,
        payload=payload,
        db=db,
        user=user,
        action="disable",
    )


@router.post("/data-sources/{data_source_id}/enable", response_model=DataSourceResponse)
def enable(
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    payload: VersionRequest,
    db: DbSession,
    user: CurrentUser,
) -> DataSourceResponse:
    return _state_change(
        workspace_id=workspace_id,
        data_source_id=data_source_id,
        payload=payload,
        db=db,
        user=user,
        action="enable",
    )


@router.delete("/data-sources/{data_source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    version: Annotated[int, Query(ge=1)],
) -> None:
    _state_change(
        workspace_id=workspace_id,
        data_source_id=data_source_id,
        payload=VersionRequest(version=version),
        db=db,
        user=user,
        action="delete",
    )


@router.get("/data-sources/{data_source_id}/jobs", response_model=list[ScanJobResponse])
def list_jobs(
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> list[ScanJobResponse]:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.DATA_SOURCE_MANAGE)
    try:
        get_data_source(db, workspace_id=workspace_id, data_source_id=data_source_id)
    except DataSourceServiceError as exc:
        raise _error(exc, status.HTTP_404_NOT_FOUND) from exc
    jobs = db.scalars(
        select(ScanJob)
        .where(
            ScanJob.workspace_id == workspace_id,
            ScanJob.data_source_id == data_source_id,
        )
        .order_by(ScanJob.created_at.desc())
    )
    return [ScanJobResponse.model_validate(job) for job in jobs]


@router.get("/scan-jobs/{job_id}", response_model=ScanJobResponse)
def job_detail(
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> ScanJobResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.DATA_SOURCE_MANAGE)
    job = db.scalar(
        select(ScanJob).where(ScanJob.id == job_id, ScanJob.workspace_id == workspace_id)
    )
    if job is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "scan_job.not_found", "message": "Scan job not found"},
        )
    return ScanJobResponse.model_validate(job)
