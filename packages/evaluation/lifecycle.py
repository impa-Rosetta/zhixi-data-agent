"""Transactional lifecycle for offline evaluations; paid execution is not enabled here."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from packages.evaluation.contracts import EvaluationSuite
from packages.evaluation.persistence import EvaluationCaseResult, EvaluationRun
from packages.evaluation.scoring import CaseScore
from packages.evaluation.versions import (
    OFFLINE_MODEL_VERSION,
    OFFLINE_PROMPT_VERSION,
    OFFLINE_TOOL_VERSION,
)
from packages.platform_core.models import AuditEvent, OutboxEvent

SAFE_ERRORS = frozenset(
    {
        "evaluation.precondition_failed",
        "evaluation.execution_failed",
        "evaluation.fixture_unavailable",
        "evaluation.cleanup_failed",
        "evaluation.suite_changed",
        "evaluation.runtime_changed",
        "evaluation.case_isolation_failed",
        "evaluation.cancelled",
        "evaluation.budget_exceeded",
        "evaluation.worker_lost",
    }
)


class EvaluationLifecycleError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class EvaluationClaim:
    run_id: uuid.UUID
    attempt_count: int


def create_offline_run(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    actor_id: uuid.UUID,
    idempotency_key: str,
    suite: EvaluationSuite,
    max_seconds: int = 300,
) -> EvaluationRun:
    if not idempotency_key or len(idempotency_key) > 100 or not 1 <= max_seconds <= 1800:
        raise EvaluationLifecycleError("evaluation.invalid_request")
    existing = db.scalar(
        select(EvaluationRun).where(
            EvaluationRun.workspace_id == workspace_id,
            EvaluationRun.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if (
            existing.created_by_user_id != actor_id
            or existing.suite_digest != suite.content_digest
            or existing.track != "offline"
            or existing.budget != {"max_seconds": max_seconds}
        ):
            raise EvaluationLifecycleError("evaluation.idempotency_conflict")
        return existing
    run = EvaluationRun(
        workspace_id=workspace_id,
        created_by_user_id=actor_id,
        idempotency_key=idempotency_key,
        suite_version=suite.suite_version,
        suite_digest=suite.content_digest,
        dataset_id=suite.synthetic_dataset_id,
        semantic_version=suite.semantic_version,
        model_version=OFFLINE_MODEL_VERSION,
        tool_version=OFFLINE_TOOL_VERSION,
        prompt_version=OFFLINE_PROMPT_VERSION,
        budget={"max_seconds": max_seconds},
        summary={},
    )
    db.add(run)
    db.flush()
    for case in suite.cases:
        db.add(
            EvaluationCaseResult(
                workspace_id=workspace_id,
                evaluation_run_id=run.id,
                case_id=case.id,
                category=case.category,
            )
        )
    db.add(
        OutboxEvent(
            aggregate_type="evaluation_run",
            aggregate_id=run.id,
            event_type="evaluation.run.requested",
            payload={"evaluation_run_id": str(run.id)},
        )
    )
    db.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=actor_id,
            action="evaluation.created",
            resource_type="evaluation_run",
            resource_id=str(run.id),
            outcome="success",
            detail=f"track=offline;cases={len(suite.cases)}",
        )
    )
    db.flush()
    return run


def scoped_run(db: Session, workspace_id: uuid.UUID, run_id: uuid.UUID) -> EvaluationRun:
    run = db.scalar(
        select(EvaluationRun).where(
            EvaluationRun.id == run_id,
            EvaluationRun.workspace_id == workspace_id,
        )
    )
    if run is None:
        raise EvaluationLifecycleError("evaluation.not_found")
    return run


def claim_run(db: Session, run_id: uuid.UUID, suite: EvaluationSuite) -> EvaluationClaim | None:
    run = db.get(EvaluationRun, run_id)
    if run is None:
        raise EvaluationLifecycleError("evaluation.not_found")
    if run.track != "offline":
        raise EvaluationLifecycleError("evaluation.live_not_enabled")
    if run.suite_digest != suite.content_digest:
        raise EvaluationLifecycleError("evaluation.suite_changed")
    if (run.model_version, run.tool_version, run.prompt_version) != (
        OFFLINE_MODEL_VERSION,
        OFFLINE_TOOL_VERSION,
        OFFLINE_PROMPT_VERSION,
    ):
        raise EvaluationLifecycleError("evaluation.runtime_changed")
    changed = db.execute(
        update(EvaluationRun)
        .where(
            EvaluationRun.id == run_id,
            EvaluationRun.status == "queued",
        )
        .values(
            status="running",
            attempt_count=EvaluationRun.attempt_count + 1,
            started_at=datetime.now(UTC),
            error_code=None,
        )
    )
    if getattr(changed, "rowcount", 0) != 1:
        return None
    db.refresh(run)
    return EvaluationClaim(run.id, run.attempt_count)


def claim_case(db: Session, claim: EvaluationClaim, case_id: str) -> int | None:
    parent = (
        select(EvaluationRun.id)
        .where(
            EvaluationRun.id == claim.run_id,
            EvaluationRun.status == "running",
            EvaluationRun.attempt_count == claim.attempt_count,
        )
        .exists()
    )
    changed = db.execute(
        update(EvaluationCaseResult)
        .where(
            EvaluationCaseResult.evaluation_run_id == claim.run_id,
            EvaluationCaseResult.case_id == case_id,
            EvaluationCaseResult.status == "queued",
            parent,
        )
        .values(
            status="running",
            started_at=datetime.now(UTC),
            attempt_count=EvaluationCaseResult.attempt_count + 1,
        )
    )
    if getattr(changed, "rowcount", 0) != 1:
        return None
    result = db.scalar(
        select(EvaluationCaseResult).where(
            EvaluationCaseResult.evaluation_run_id == claim.run_id,
            EvaluationCaseResult.case_id == case_id,
        )
    )
    assert result is not None
    return result.attempt_count


def finish_case(
    db: Session,
    claim: EvaluationClaim,
    score: CaseScore,
    *,
    case_attempt: int,
    duration_ms: int,
    run_references: tuple[uuid.UUID, ...] = (),
) -> bool:
    if duration_ms < 0:
        raise EvaluationLifecycleError("evaluation.invalid_duration")
    parent = (
        select(EvaluationRun.id)
        .where(
            EvaluationRun.id == claim.run_id,
            EvaluationRun.status == "running",
            EvaluationRun.attempt_count == claim.attempt_count,
        )
        .exists()
    )
    error = score.error_code
    if error is not None and error not in SAFE_ERRORS:
        error = "evaluation.execution_failed"
    changed = db.execute(
        update(EvaluationCaseResult)
        .where(
            EvaluationCaseResult.evaluation_run_id == claim.run_id,
            EvaluationCaseResult.case_id == score.case_id,
            EvaluationCaseResult.status == "running",
            EvaluationCaseResult.attempt_count == case_attempt,
            parent,
        )
        .values(
            status=score.status,
            duration_ms=duration_ms,
            finished_at=datetime.now(UTC),
            assertion_results=[
                {"name": check.name, "passed": check.passed} for check in score.checks
            ],
            run_references=[str(ref) for ref in run_references],
            error_code=error,
        )
    )
    return getattr(changed, "rowcount", 0) == 1


def cancel_run(
    db: Session, workspace_id: uuid.UUID, run_id: uuid.UUID, actor_id: uuid.UUID
) -> None:
    scoped_run(db, workspace_id, run_id)
    changed = db.execute(
        update(EvaluationRun)
        .where(
            EvaluationRun.id == run_id,
            EvaluationRun.workspace_id == workspace_id,
            EvaluationRun.status.in_(["queued", "running"]),
        )
        .values(
            status="cancelled", finished_at=datetime.now(UTC), error_code="evaluation.cancelled"
        )
    )
    if getattr(changed, "rowcount", 0) != 1:
        raise EvaluationLifecycleError("evaluation.cancel_conflict")
    db.execute(
        update(EvaluationCaseResult)
        .where(
            EvaluationCaseResult.evaluation_run_id == run_id,
            EvaluationCaseResult.status.in_(["queued", "running"]),
        )
        .values(status="blocked", error_code="evaluation.cancelled", finished_at=datetime.now(UTC))
    )
    db.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=actor_id,
            action="evaluation.cancelled",
            resource_type="evaluation_run",
            resource_id=str(run_id),
            outcome="success",
        )
    )


def fail_queued_run(db: Session, run_id: uuid.UUID, error_code: str) -> bool:
    if error_code not in SAFE_ERRORS:
        error_code = "evaluation.precondition_failed"
    changed = db.execute(
        update(EvaluationRun)
        .where(
            EvaluationRun.id == run_id,
            EvaluationRun.status == "queued",
            EvaluationRun.track == "offline",
        )
        .values(status="failed", error_code=error_code, finished_at=datetime.now(UTC))
    )
    if getattr(changed, "rowcount", 0) != 1:
        return False
    db.execute(
        update(EvaluationCaseResult)
        .where(
            EvaluationCaseResult.evaluation_run_id == run_id,
            EvaluationCaseResult.status == "queued",
        )
        .values(status="blocked", error_code=error_code, finished_at=datetime.now(UTC))
    )
    return True


def resume_offline_run(
    db: Session,
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> None:
    run = scoped_run(db, workspace_id, run_id)
    if run.track != "offline" or run.attempt_count >= 3:
        raise EvaluationLifecycleError("evaluation.resume_not_allowed")
    changed = db.execute(
        update(EvaluationRun)
        .where(
            EvaluationRun.id == run_id,
            EvaluationRun.workspace_id == workspace_id,
            EvaluationRun.status == "partial",
            EvaluationRun.error_code == "evaluation.worker_lost",
            EvaluationRun.attempt_count == run.attempt_count,
        )
        .values(
            status="queued",
            error_code=None,
            started_at=datetime.now(UTC),
            finished_at=None,
            summary={},
        )
    )
    if getattr(changed, "rowcount", 0) != 1:
        raise EvaluationLifecycleError("evaluation.resume_not_allowed")
    db.execute(
        update(EvaluationCaseResult)
        .where(
            EvaluationCaseResult.evaluation_run_id == run_id,
            EvaluationCaseResult.status == "infra_error",
            EvaluationCaseResult.error_code == "evaluation.worker_lost",
        )
        .values(status="queued", error_code=None, started_at=None, finished_at=None)
    )
    db.add(
        OutboxEvent(
            aggregate_type="evaluation_run",
            aggregate_id=run_id,
            event_type="evaluation.run.requested",
            payload={"evaluation_run_id": str(run_id)},
        )
    )
    db.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=actor_id,
            action="evaluation.resumed",
            resource_type="evaluation_run",
            resource_id=str(run_id),
            outcome="success",
        )
    )


def recover_offline_runs(db: Session, *, now: datetime | None = None) -> int:
    current = now or datetime.now(UTC)
    runs = list(
        db.scalars(
            select(EvaluationRun)
            .where(
                EvaluationRun.track == "offline",
                EvaluationRun.status.in_(["queued", "running"]),
                func.coalesce(EvaluationRun.started_at, EvaluationRun.created_at)
                < current - timedelta(minutes=35),
            )
            .limit(100)
        )
    )
    recovered = 0
    for run in runs:
        changed = db.execute(
            update(EvaluationRun)
            .where(
                EvaluationRun.id == run.id,
                EvaluationRun.status == run.status,
                EvaluationRun.attempt_count == run.attempt_count,
            )
            .values(status="partial", error_code="evaluation.worker_lost", finished_at=current)
        )
        if getattr(changed, "rowcount", 0) != 1:
            continue
        db.execute(
            update(EvaluationCaseResult)
            .where(
                EvaluationCaseResult.evaluation_run_id == run.id,
                EvaluationCaseResult.status.in_(["queued", "running"]),
            )
            .values(status="infra_error", error_code="evaluation.worker_lost", finished_at=current)
        )
        recovered += 1
    return recovered
