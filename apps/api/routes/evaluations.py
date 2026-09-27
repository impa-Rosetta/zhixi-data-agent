from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from apps.api.authorization import authorize
from apps.api.dependencies import CurrentUser, DbSession
from packages.evaluation.lifecycle import (
    EvaluationLifecycleError,
    cancel_run,
    create_offline_run,
    resume_offline_run,
    scoped_run,
)
from packages.evaluation.persistence import EvaluationCaseResult, EvaluationRun
from packages.evaluation.registry import SUITE_VERSIONS, registered_suite
from packages.platform_core.policy import Action
from packages.platform_core.settings import get_settings
from packages.shared_contracts.evaluations import (
    CreateEvaluationRequest,
    EvaluationCaseResponse,
    EvaluationRunResponse,
)

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/evaluations", tags=["evaluations"])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=100)]


def _error(error: EvaluationLifecycleError) -> HTTPException:
    return HTTPException(
        404 if error.code == "evaluation.not_found" else 409,
        detail={"code": error.code, "message": "评测操作未完成，请刷新后重试。"},
    )


@router.get("/suites")
def suites(workspace_id: UUID, db: DbSession, user: CurrentUser) -> dict[str, object]:
    membership = authorize(db, user=user, workspace_id=workspace_id, action=Action.EVALUATION_READ)
    items = []
    for version in SUITE_VERSIONS:
        suite = registered_suite(version)
        counts = {
            category: sum(case.category == category for case in suite.cases)
            for category in ("standard", "multi_turn", "ambiguity", "anomaly", "security")
        }
        items.append(
            {
                "suite_version": version,
                "suite_digest": suite.content_digest,
                "published": suite.published,
                "case_count": len(suite.cases),
                "category_counts": counts,
                "dataset_id": suite.synthetic_dataset_id,
            }
        )
    return {
        "items": items,
        "offline_enabled": get_settings().evaluation_offline_enabled,
        "live_enabled": False,
        "can_manage": membership.role.value in {"system_admin", "workspace_admin"},
    }


@router.get("")
def index(
    workspace_id: UUID,
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.EVALUATION_READ)
    query = select(EvaluationRun).where(EvaluationRun.workspace_id == workspace_id)
    count = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    runs = db.scalars(
        query.order_by(EvaluationRun.created_at.desc(), EvaluationRun.id)
        .limit(limit)
        .offset(offset)
    )
    return {
        "items": [EvaluationRunResponse.model_validate(run) for run in runs],
        "total": count,
        "limit": limit,
        "offset": offset,
    }


@router.post("", response_model=EvaluationRunResponse, status_code=201)
def create(
    workspace_id: UUID,
    payload: CreateEvaluationRequest,
    idempotency_key: IdempotencyKey,
    db: DbSession,
    user: CurrentUser,
) -> EvaluationRunResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.EVALUATION_MANAGE)
    if not get_settings().evaluation_offline_enabled:
        raise HTTPException(
            503, detail={"code": "evaluation.offline_disabled", "message": "尚未启用隔离评测环境。"}
        )
    try:
        suite = registered_suite(payload.suite_version)
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "evaluation.suite_not_registered"}) from exc
    try:
        run = create_offline_run(
            db,
            workspace_id=workspace_id,
            actor_id=user.id,
            idempotency_key=idempotency_key,
            suite=suite,
            max_seconds=payload.max_seconds,
        )
        db.commit()
    except EvaluationLifecycleError as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            409,
            detail={
                "code": "evaluation.concurrent_request",
                "message": "请求发生冲突，请刷新后重试。",
            },
        ) from exc
    return EvaluationRunResponse.model_validate(run)


@router.get("/{run_id}", response_model=EvaluationRunResponse)
def detail(
    workspace_id: UUID, run_id: UUID, db: DbSession, user: CurrentUser
) -> EvaluationRunResponse:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.EVALUATION_READ)
    try:
        return EvaluationRunResponse.model_validate(scoped_run(db, workspace_id, run_id))
    except EvaluationLifecycleError as exc:
        raise _error(exc) from exc


@router.get("/{run_id}/cases")
def cases(
    workspace_id: UUID,
    run_id: UUID,
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.EVALUATION_READ)
    try:
        scoped_run(db, workspace_id, run_id)
    except EvaluationLifecycleError as exc:
        raise _error(exc) from exc
    query = select(EvaluationCaseResult).where(
        EvaluationCaseResult.workspace_id == workspace_id,
        EvaluationCaseResult.evaluation_run_id == run_id,
    )
    count = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    results = db.scalars(query.order_by(EvaluationCaseResult.case_id).limit(limit).offset(offset))
    return {
        "items": [EvaluationCaseResponse.model_validate(item) for item in results],
        "total": count,
        "limit": limit,
        "offset": offset,
    }


@router.post("/{run_id}/cancel", status_code=204)
def cancel(workspace_id: UUID, run_id: UUID, db: DbSession, user: CurrentUser) -> None:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.EVALUATION_MANAGE)
    try:
        cancel_run(db, workspace_id, run_id, user.id)
        db.commit()
    except EvaluationLifecycleError as exc:
        db.rollback()
        raise _error(exc) from exc


@router.post("/{run_id}/resume", status_code=204)
def resume(workspace_id: UUID, run_id: UUID, db: DbSession, user: CurrentUser) -> None:
    authorize(db, user=user, workspace_id=workspace_id, action=Action.EVALUATION_MANAGE)
    if not get_settings().evaluation_offline_enabled:
        raise HTTPException(503, detail={"code": "evaluation.offline_disabled"})
    try:
        resume_offline_run(db, workspace_id, run_id, user.id)
        db.commit()
    except EvaluationLifecycleError as exc:
        db.rollback()
        raise _error(exc) from exc
