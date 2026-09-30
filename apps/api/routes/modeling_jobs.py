"""Feature-gated modeling job endpoints; never execute models in API."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status
from sqlalchemy import select

from apps.api.authorization import authorize
from apps.api.dependencies import CurrentUser, DbSession
from apps.api.services.modeling_jobs import create_training_job
from packages.modeling.contracts import ModelSpec
from packages.modeling.data import ModelDataError
from packages.modeling.job_store import cancel_job
from packages.modeling.object_storage import MinioModelObjectStorage
from packages.modeling.persistence import ModelJob, ModelVersion
from packages.platform_core.policy import Action
from packages.platform_core.settings import get_settings
from packages.shared_contracts.modeling import ModelJobResponse

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/model-jobs", tags=["modeling"])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=100)]


def _require_enabled() -> None:
    if not get_settings().modeling_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Modeling is not enabled")


def _storage() -> MinioModelObjectStorage:
    settings = get_settings()
    return MinioModelObjectStorage(
        endpoint_url=settings.s3_endpoint_url,
        access_key=settings.s3_access_key.get_secret_value(),
        secret_key=settings.s3_secret_key.get_secret_value(),
        bucket=settings.s3_bucket,
    )


def _job(
    db: DbSession, workspace_id: uuid.UUID, job_id: uuid.UUID, actor_id: uuid.UUID
) -> ModelJob:
    job = db.scalar(
        select(ModelJob).where(
            ModelJob.id == job_id,
            ModelJob.workspace_id == workspace_id,
            ModelJob.created_by_user_id == actor_id,
        )
    )
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Model job not found")
    return job


def _view(db: DbSession, job: ModelJob) -> ModelJobResponse:
    version_id = db.scalar(select(ModelVersion.id).where(ModelVersion.training_job_id == job.id))
    return ModelJobResponse.model_validate(
        {
            "id": job.id,
            "status": job.status,
            "attempt_count": job.attempt_count,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "model_version_id": version_id,
            "error_code": job.error_code,
        }
    )


@router.post("", response_model=ModelJobResponse, status_code=status.HTTP_201_CREATED)
def create(
    workspace_id: uuid.UUID,
    spec: ModelSpec,
    idempotency_key: IdempotencyKey,
    db: DbSession,
    user: CurrentUser,
) -> ModelJobResponse:
    _require_enabled()
    authorize(db, user=user, workspace_id=workspace_id, action=Action.MODEL_TRAIN)
    try:
        storage = _storage()
        job, _ = create_training_job(
            db,
            workspace_id=workspace_id,
            actor_user_id=user.id,
            idempotency_key=idempotency_key,
            spec=spec,
            storage=storage,
        )
        view = _view(db, job)
        db.commit()
        return view
    except ModelDataError as exc:
        db.rollback()
        code = str(exc)
        http_status = status.HTTP_403_FORBIDDEN if code == "policy.denied" else 409
        raise HTTPException(http_status, detail={"code": code}) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "model.service_unavailable"},
        ) from exc


@router.get("/{job_id}", response_model=ModelJobResponse)
def detail(
    workspace_id: uuid.UUID, job_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> ModelJobResponse:
    _require_enabled()
    authorize(db, user=user, workspace_id=workspace_id, action=Action.MODEL_READ)
    return _view(db, _job(db, workspace_id, job_id, user.id))


@router.post("/{job_id}/cancel", response_model=ModelJobResponse)
def cancel(
    workspace_id: uuid.UUID, job_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> ModelJobResponse:
    _require_enabled()
    authorize(db, user=user, workspace_id=workspace_id, action=Action.MODEL_TRAIN)
    job = _job(db, workspace_id, job_id, user.id)
    cancel_job(db, workspace_id=workspace_id, job_id=job.id)
    db.commit()
    db.refresh(job)
    return _view(db, job)
