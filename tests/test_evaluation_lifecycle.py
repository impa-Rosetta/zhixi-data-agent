import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from test_evaluation_persistence import _database

from packages.evaluation import load_suite
from packages.evaluation.lifecycle import (
    EvaluationLifecycleError,
    cancel_run,
    claim_case,
    claim_run,
    create_offline_run,
    finish_case,
    recover_offline_runs,
    resume_offline_run,
    scoped_run,
)
from packages.evaluation.persistence import EvaluationCaseResult
from packages.evaluation.scoring import CaseScore, CheckScore
from packages.platform_core.models import OutboxEvent


def _created():
    db, fixture = _database()
    suite = load_suite(Path("evaluations/golden/manufacturing-quality-draft-v0.1.2.json"))
    run = create_offline_run(
        db,
        workspace_id=fixture.workspace_id,
        actor_id=fixture.created_by_user_id,
        idempotency_key="created",
        suite=suite,
    )
    db.commit()
    return db, run, suite


def test_create_freezes_versions_and_enqueues_once() -> None:
    db, run, suite = _created()
    again = create_offline_run(
        db,
        workspace_id=run.workspace_id,
        actor_id=run.created_by_user_id,
        idempotency_key="created",
        suite=suite,
    )
    db.commit()
    assert again.id == run.id
    assert run.suite_digest == suite.content_digest
    from packages.evaluation.postgres_draft_adapter import ADAPTER_VERSION

    assert run.tool_version == ADAPTER_VERSION
    assert db.scalar(select(func.count()).select_from(EvaluationCaseResult)) == 9
    assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 1
    with pytest.raises(EvaluationLifecycleError, match="idempotency_conflict"):
        create_offline_run(
            db,
            workspace_id=run.workspace_id,
            actor_id=run.created_by_user_id,
            idempotency_key="created",
            suite=suite,
            max_seconds=60,
        )
    db.close()


@pytest.mark.parametrize("field", ["model_version", "tool_version", "prompt_version"])
def test_runtime_drift_is_rejected_before_claiming_any_case(field) -> None:
    db, run, suite = _created()
    setattr(run, field, "older-runtime")
    db.commit()
    with pytest.raises(EvaluationLifecycleError, match="runtime_changed"):
        claim_run(db, run.id, suite)
    assert run.status == "queued" and run.attempt_count == 0
    assert (
        db.scalar(
            select(func.count())
            .select_from(EvaluationCaseResult)
            .where(EvaluationCaseResult.attempt_count != 0)
        )
        == 0
    )
    db.close()


def test_claim_is_conditional_and_suite_digest_is_checked() -> None:
    db, run, suite = _created()
    with pytest.raises(EvaluationLifecycleError, match="suite_changed"):
        claim_run(db, run.id, suite.model_copy(update={"semantic_version": "changed"}))
    claim = claim_run(db, run.id, suite)
    assert claim is not None
    db.commit()
    assert claim_run(db, run.id, suite) is None
    assert run.attempt_count == 1
    db.close()


def test_claim_case_cannot_be_consumed_twice() -> None:
    db, run, suite = _created()
    claim = claim_run(db, run.id, suite)
    assert claim is not None
    case_id = suite.cases[0].id
    assert claim_case(db, claim, case_id) == 1
    db.commit()
    assert claim_case(db, claim, case_id) is None
    assert finish_case(
        db,
        claim,
        CaseScore(case_id, "passed", (CheckScore("status", True),)),
        case_attempt=1,
        duration_ms=10,
    )
    db.commit()
    assert not finish_case(
        db, claim, CaseScore(case_id, "failed", ()), case_attempt=1, duration_ms=20
    )
    db.close()


def test_cancellation_prevents_late_worker_publication() -> None:
    db, run, suite = _created()
    claim = claim_run(db, run.id, suite)
    assert claim is not None
    case_id = suite.cases[0].id
    assert claim_case(db, claim, case_id) == 1
    db.commit()
    cancel_run(db, run.workspace_id, run.id, run.created_by_user_id)
    db.commit()
    assert not finish_case(
        db, claim, CaseScore(case_id, "passed", ()), case_attempt=1, duration_ms=0
    )
    assert claim_case(db, claim, suite.cases[1].id) is None
    assert all(item.status == "blocked" for item in db.scalars(select(EvaluationCaseResult)))
    db.close()


def test_scoped_access_hides_other_workspaces() -> None:
    db, run, _ = _created()
    with pytest.raises(EvaluationLifecycleError, match="not_found"):
        scoped_run(db, uuid.uuid4(), run.id)
    with pytest.raises(EvaluationLifecycleError, match="not_found"):
        cancel_run(db, uuid.uuid4(), run.id, run.created_by_user_id)
    db.close()


def test_recovery_preserves_completed_cases_and_rejects_late_claims() -> None:
    db, run, suite = _created()
    claim = claim_run(db, run.id, suite)
    assert claim is not None
    case_id = suite.cases[0].id
    assert claim_case(db, claim, case_id) == 1
    assert finish_case(db, claim, CaseScore(case_id, "passed", ()), case_attempt=1, duration_ms=0)
    run.started_at = datetime.now(UTC) - timedelta(hours=1)
    db.commit()
    assert recover_offline_runs(db) == 1
    db.commit()
    assert run.status == "partial"
    statuses = [item.status for item in db.scalars(select(EvaluationCaseResult))]
    assert statuses.count("passed") == 1 and statuses.count("infra_error") == 8
    assert recover_offline_runs(db) == 0
    db.close()


def test_error_payload_does_not_store_provider_secrets() -> None:
    db, run, suite = _created()
    claim = claim_run(db, run.id, suite)
    assert claim is not None
    case_id = suite.cases[0].id
    assert claim_case(db, claim, case_id) == 1
    assert finish_case(
        db,
        claim,
        CaseScore(case_id, "infra_error", (), "raw secret payload"),
        case_attempt=1,
        duration_ms=1,
    )
    db.commit()
    case = db.scalar(select(EvaluationCaseResult).where(EvaluationCaseResult.case_id == case_id))
    assert case is not None and case.error_code == "evaluation.execution_failed"
    db.close()


def test_lost_queued_delivery_can_be_recovered_without_immediate_expiry_on_resume() -> None:
    db, run, _ = _created()
    run.created_at = datetime.now(UTC) - timedelta(hours=1)
    db.commit()
    assert recover_offline_runs(db) == 1
    db.commit()
    assert run.status == "partial" and run.attempt_count == 0
    resume_offline_run(db, run.workspace_id, run.id, run.created_by_user_id)
    db.commit()
    assert recover_offline_runs(db) == 0
    assert run.status == "queued"
    assert all(item.status == "queued" for item in db.scalars(select(EvaluationCaseResult)))
    db.close()
