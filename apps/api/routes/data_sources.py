import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from apps.api.authorization import authorize
from apps.api.dependencies import CurrentUser, DbSession
from apps.api.services.catalogs import get_catalog, list_diffs, list_snapshots
from apps.api.services.data_sources import (
    DataSourceServiceError,
    change_data_source_state,
    create_data_source,
    enqueue_connection_test,
    enqueue_metadata_scan,
    get_data_source,
    list_data_sources,
    update_data_source,
)
from apps.api.services.profiles import get_snapshot_column_profile, list_snapshot_profiles
from apps.api.services.sampling import (
    get_sampling_policy,
    get_scan_schedule,
    update_sampling_policy,
    update_scan_schedule,
)
from apps.api.services.scan_jobs import request_scan_job_cancel, retry_scan_job
from packages.platform_core.models import ScanJob, ScanJobTrigger
from packages.platform_core.policy import Action
from packages.platform_core.settings import get_settings
from packages.shared_contracts.data_sources import (
    CatalogColumnProfileResponse,
    CatalogDiffPage,
    CatalogDiffResponse,
    CatalogProfileListResponse,
    CatalogRelationResponse,
    CatalogResponse,
    CatalogSchemaResponse,
    CatalogSnapshotResponse,
    DataSourceCreateRequest,
    DataSourceCreateResponse,
    DataSourcePage,
    DataSourceResponse,
    DataSourceUpdateRequest,
    MetadataScanRequest,
    SamplingPolicyResponse,
    SamplingPolicyUpdateRequest,
    ScanJobResponse,
    ScanScheduleResponse,
    ScanScheduleUpdateRequest,
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
        "data_source.not_ready",
        "catalog.not_available",
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
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "data_source.conflict",
                "message": "A data source with the same name already exists",
            },
        ) from exc
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


@router.post(
    "/data-sources/{data_source_id}/scans",
    response_model=ScanJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def scan(
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    payload: MetadataScanRequest,
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
        job = enqueue_metadata_scan(
            db,
            source=source,
            actor_user_id=user.id,
            trigger=ScanJobTrigger.MANUAL,
            schemas=tuple(payload.schemas),
            idempotency_token=idempotency_key,
        )
    except DataSourceServiceError as exc:
        db.rollback()
        raise _error(exc, _service_status(exc, status.HTTP_409_CONFLICT)) from exc
    _commit(db)
    db.refresh(job)
    return ScanJobResponse.model_validate(job)


@router.get(
    "/data-sources/{data_source_id}/sampling-policy",
    response_model=SamplingPolicyResponse,
)
def sampling_policy(
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> SamplingPolicyResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.CATALOG_READ)
    try:
        return get_sampling_policy(db, workspace_id=workspace_id, data_source_id=data_source_id)
    except DataSourceServiceError as exc:
        raise _error(exc, status.HTTP_404_NOT_FOUND) from exc


@router.put(
    "/data-sources/{data_source_id}/sampling-policy",
    response_model=SamplingPolicyResponse,
)
def put_sampling_policy(
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    payload: SamplingPolicyUpdateRequest,
    db: DbSession,
    user: CurrentUser,
) -> SamplingPolicyResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.DATA_SOURCE_MANAGE)
    try:
        stored = update_sampling_policy(
            db,
            workspace_id=workspace_id,
            data_source_id=data_source_id,
            actor_user_id=user.id,
            payload=payload,
        )
    except DataSourceServiceError as exc:
        db.rollback()
        code = (
            status.HTTP_409_CONFLICT
            if exc.code == "sampling.version_conflict"
            else _service_status(exc, status.HTTP_422_UNPROCESSABLE_CONTENT)
        )
        raise _error(exc, code) from exc
    _commit(db)
    db.refresh(stored)
    return SamplingPolicyResponse.model_validate(stored)


@router.get(
    "/data-sources/{data_source_id}/schedule",
    response_model=ScanScheduleResponse,
)
def schedule(
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> ScanScheduleResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.CATALOG_READ)
    try:
        stored = get_scan_schedule(db, workspace_id=workspace_id, data_source_id=data_source_id)
    except DataSourceServiceError as exc:
        raise _error(exc, status.HTTP_404_NOT_FOUND) from exc
    return ScanScheduleResponse.model_validate(stored)


@router.put(
    "/data-sources/{data_source_id}/schedule",
    response_model=ScanScheduleResponse,
)
def put_schedule(
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    payload: ScanScheduleUpdateRequest,
    db: DbSession,
    user: CurrentUser,
) -> ScanScheduleResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.DATA_SOURCE_MANAGE)
    try:
        stored = update_scan_schedule(
            db,
            workspace_id=workspace_id,
            data_source_id=data_source_id,
            actor_user_id=user.id,
            payload=payload,
        )
    except DataSourceServiceError as exc:
        db.rollback()
        code = (
            status.HTTP_409_CONFLICT
            if exc.code == "schedule.version_conflict"
            else _service_status(exc, status.HTTP_422_UNPROCESSABLE_CONTENT)
        )
        raise _error(exc, code) from exc
    _commit(db)
    db.refresh(stored)
    return ScanScheduleResponse.model_validate(stored)


@router.get(
    "/data-sources/{data_source_id}/snapshots",
    response_model=list[CatalogSnapshotResponse],
)
def snapshots(
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> list[CatalogSnapshotResponse]:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.CATALOG_READ)
    try:
        items = list_snapshots(db, workspace_id=workspace_id, data_source_id=data_source_id)
    except DataSourceServiceError as exc:
        raise _error(exc, status.HTTP_404_NOT_FOUND) from exc
    return [CatalogSnapshotResponse.model_validate(item) for item in items]


@router.get("/data-sources/{data_source_id}/catalog", response_model=CatalogResponse)
def catalog(
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    snapshot_id: uuid.UUID | None = None,
) -> CatalogResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.CATALOG_READ)
    try:
        snapshot, document = get_catalog(
            db,
            workspace_id=workspace_id,
            data_source_id=data_source_id,
            snapshot_id=snapshot_id,
        )
    except DataSourceServiceError as exc:
        code = (
            status.HTTP_409_CONFLICT
            if exc.code == "catalog.not_available"
            else status.HTTP_404_NOT_FOUND
        )
        raise _error(exc, code) from exc
    schemas = []
    for item in document.schemas:
        relations = [
            CatalogRelationResponse.model_validate(relation)
            for relation in document.relations
            if relation.schema == item.name
        ]
        schemas.append(
            CatalogSchemaResponse(name=item.name, comment=item.comment, relations=relations)
        )
    return CatalogResponse(
        snapshot=CatalogSnapshotResponse.model_validate(snapshot), schemas=schemas
    )


@router.get(
    "/data-sources/{data_source_id}/catalog/snapshots/{snapshot_id}/profiles",
    response_model=CatalogProfileListResponse,
)
def profiles(
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> CatalogProfileListResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.CATALOG_READ)
    try:
        return list_snapshot_profiles(
            db,
            workspace_id=workspace_id,
            data_source_id=data_source_id,
            snapshot_id=snapshot_id,
        )
    except DataSourceServiceError as exc:
        raise _error(exc, status.HTTP_404_NOT_FOUND) from exc


@router.get(
    "/data-sources/{data_source_id}/catalog/snapshots/{snapshot_id}/profiles/{column_id}",
    response_model=CatalogColumnProfileResponse,
)
def profile_detail(
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    column_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> CatalogColumnProfileResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.CATALOG_READ)
    try:
        return get_snapshot_column_profile(
            db,
            workspace_id=workspace_id,
            data_source_id=data_source_id,
            snapshot_id=snapshot_id,
            column_id=column_id,
        )
    except DataSourceServiceError as exc:
        raise _error(exc, status.HTTP_404_NOT_FOUND) from exc


@router.get("/data-sources/{data_source_id}/diffs", response_model=CatalogDiffPage)
def diffs(
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    to_snapshot_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CatalogDiffPage:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.CATALOG_READ)
    try:
        items, total = list_diffs(
            db,
            workspace_id=workspace_id,
            data_source_id=data_source_id,
            to_snapshot_id=to_snapshot_id,
            limit=limit,
            offset=offset,
        )
    except DataSourceServiceError as exc:
        raise _error(exc, status.HTTP_404_NOT_FOUND) from exc
    return CatalogDiffPage(
        items=[CatalogDiffResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


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


@router.post("/scan-jobs/{job_id}/cancel", response_model=ScanJobResponse)
def cancel_job(
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> ScanJobResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.DATA_SOURCE_MANAGE)
    try:
        job = request_scan_job_cancel(
            db,
            workspace_id=workspace_id,
            job_id=job_id,
            actor_user_id=user.id,
        )
    except DataSourceServiceError as exc:
        raise _error(exc, status.HTTP_404_NOT_FOUND) from exc
    _commit(db)
    db.refresh(job)
    return ScanJobResponse.model_validate(job)


@router.post("/scan-jobs/{job_id}/retry", response_model=ScanJobResponse)
def retry_job(
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
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
        job = retry_scan_job(
            db,
            workspace_id=workspace_id,
            job_id=job_id,
            actor_user_id=user.id,
            idempotency_token=idempotency_key,
        )
    except DataSourceServiceError as exc:
        code = (
            status.HTTP_404_NOT_FOUND
            if exc.code in {"scan_job.not_found", "catalog.not_found"}
            else status.HTTP_409_CONFLICT
        )
        raise _error(exc, code) from exc
    _commit(db)
    db.refresh(job)
    return ScanJobResponse.model_validate(job)
