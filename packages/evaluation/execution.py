"""Run the production offline adapter with durable, fenced per-case results."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from packages.evaluation.contracts import EvaluationSuite
from packages.evaluation.lifecycle import (
    EvaluationClaim,
    claim_case,
    claim_run,
    finish_case,
)
from packages.evaluation.persistence import EvaluationCaseResult, EvaluationRun
from packages.evaluation.runner import OfflineCaseFactory, run_offline_suite
from packages.platform_core.models import AuditEvent


def finish_run(db: Session, claim: EvaluationClaim, *, error_code: str | None = None) -> bool:
    if error_code is not None:
        db.execute(
            update(EvaluationCaseResult)
            .where(
                EvaluationCaseResult.evaluation_run_id == claim.run_id,
                EvaluationCaseResult.status.in_(["queued", "running"]),
                select(EvaluationRun.id)
                .where(
                    EvaluationRun.id == claim.run_id,
                    EvaluationRun.status == "running",
                    EvaluationRun.attempt_count == claim.attempt_count,
                )
                .exists(),
            )
            .values(status="blocked", error_code=error_code, finished_at=datetime.now(UTC))
        )
    cases = list(
        db.scalars(
            select(EvaluationCaseResult).where(
                EvaluationCaseResult.evaluation_run_id == claim.run_id,
            )
        )
    )
    counts = {
        state: sum(case.status == state for case in cases)
        for state in ("passed", "failed", "infra_error", "blocked", "queued", "running")
    }
    evaluated = counts["passed"] + counts["failed"]
    total = len(cases)
    summary: dict[str, object] = {
        "total": total,
        **counts,
        "evaluated_pass_rate": counts["passed"] / evaluated if evaluated else None,
        "coverage_rate": evaluated / total if total else 0,
        "all_case_pass_rate": counts["passed"] / total if total else 0,
        "safety_failure_ids": [
            case.case_id
            for case in cases
            if case.category == "security" and case.status == "failed"
        ],
    }
    if counts["queued"] or counts["running"]:
        return False
    changed = db.execute(
        update(EvaluationRun)
        .where(
            EvaluationRun.id == claim.run_id,
            EvaluationRun.status == "running",
            EvaluationRun.attempt_count == claim.attempt_count,
        )
        .values(
            status="partial"
            if error_code or counts["infra_error"] or counts["blocked"]
            else "completed",
            finished_at=datetime.now(UTC),
            summary=summary,
            error_code=error_code,
        )
    )
    saved = getattr(changed, "rowcount", 0) == 1
    if saved:
        run = db.get(EvaluationRun, claim.run_id)
        assert run is not None
        db.add(
            AuditEvent(
                workspace_id=run.workspace_id,
                actor_user_id=run.created_by_user_id,
                action="evaluation.finished",
                resource_type="evaluation_run",
                resource_id=str(run.id),
                outcome="success" if run.status == "completed" else "partial",
                detail=f"evaluated={evaluated};total={total}",
            )
        )
    return saved


def execute_offline_run(
    engine: Engine,
    run_id: uuid.UUID,
    suite: EvaluationSuite,
    factory: OfflineCaseFactory,
) -> None:
    with Session(engine) as db:
        claim = claim_run(db, run_id, suite)
        db.commit()
        if claim is None:
            return
        run = db.get(EvaluationRun, run_id)
        assert run is not None
        max_seconds = run.budget.get("max_seconds")
        if (
            not isinstance(max_seconds, int)
            or isinstance(max_seconds, bool)
            or not 1 <= max_seconds <= 1800
        ):
            finish_run(db, claim, error_code="evaluation.precondition_failed")
            db.commit()
            return
        used_references = {
            uuid.UUID(reference)
            for completed in db.scalars(
                select(EvaluationCaseResult).where(
                    EvaluationCaseResult.evaluation_run_id == run_id,
                    EvaluationCaseResult.status.in_(["passed", "failed"]),
                )
            )
            for reference in completed.run_references
        }
    started = time.monotonic()
    for case in suite.cases:
        with Session(engine) as db:
            if time.monotonic() - started >= max_seconds:
                finish_run(db, claim, error_code="evaluation.budget_exceeded")
                db.commit()
                return
            attempt = claim_case(db, claim, case.id)
            db.commit()
            if attempt is None:
                current = db.get(EvaluationRun, run_id)
                if current is None or current.status != "running":
                    return
                continue
        case_started = time.monotonic()
        result = run_offline_suite(suite, factory, case_ids=frozenset({case.id}))
        references = result.run_references.get(case.id, ())
        with Session(engine) as db:
            if used_references.intersection(references):
                finish_run(db, claim, error_code="evaluation.case_isolation_failed")
                db.commit()
                return
            used_references.update(references)
            if case.id in result.blocked_case_ids:
                finish_run(db, claim, error_code="evaluation.precondition_failed")
                db.commit()
                return
            if not result.scores:
                finish_run(db, claim, error_code="evaluation.execution_failed")
                db.commit()
                return
            saved = finish_case(
                db,
                claim,
                result.scores[0],
                case_attempt=attempt,
                duration_ms=max(0, int((time.monotonic() - case_started) * 1000)),
                run_references=references,
            )
            db.commit()
            if not saved:
                return
            if result.stopped_reason:
                finish_run(db, claim, error_code=result.stopped_reason)
                db.commit()
                return
            if time.monotonic() - started >= max_seconds:
                finish_run(db, claim, error_code="evaluation.budget_exceeded")
                db.commit()
                return
    with Session(engine) as db:
        finish_run(db, claim)
        db.commit()
