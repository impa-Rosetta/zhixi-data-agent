import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session
from test_evaluation_model_budget import _live
from test_evaluation_persistence import _database

from apps.worker.tasks import evaluations as tasks
from packages.evaluation.lifecycle import EvaluationLifecycleError
from packages.evaluation.model_budget import reserve_call
from packages.evaluation.persistence import EvaluationCaseResult, EvaluationModelCall, EvaluationRun
from packages.evaluation.registry import registered_suite


@pytest.fixture
def worker_context(monkeypatch):
    db, run = _database()
    engine = db.get_bind()
    assert isinstance(engine, Engine)
    run_id = run.id
    db.add(
        EvaluationCaseResult(
            workspace_id=run.workspace_id,
            evaluation_run_id=run.id,
            case_id="worker-fixture",
            category="standard",
        )
    )
    db.commit()
    db.close()
    monkeypatch.setattr(tasks, "get_engine", lambda: engine)
    monkeypatch.setattr(
        tasks, "get_settings", lambda: SimpleNamespace(evaluation_offline_enabled=True)
    )
    execute = Mock()
    monkeypatch.setattr(tasks, "execute_offline_run", execute)
    try:
        yield engine, run_id, execute
    finally:
        engine.dispose()


def test_disabled_evaluation_commits_safe_failure_without_execution(worker_context, monkeypatch):
    engine, run_id, execute = worker_context
    monkeypatch.setattr(
        tasks, "get_settings", lambda: SimpleNamespace(evaluation_offline_enabled=False)
    )
    tasks.execute_evaluation.run(str(run_id))
    execute.assert_not_called()
    with Session(engine) as db:
        run = db.get(EvaluationRun, run_id)
        case = db.scalar(select(EvaluationCaseResult))
        assert run is not None and case is not None
        assert run.status == "failed" and run.error_code == "evaluation.precondition_failed"
        assert case.status == "blocked" and case.error_code == run.error_code
        assert run.finished_at is not None and case.finished_at is not None


@pytest.mark.parametrize("status", ["running", "completed", "cancelled"])
def test_disabled_evaluation_does_not_overwrite_nonqueued_state(
    worker_context, monkeypatch, status
):
    engine, run_id, execute = worker_context
    with Session(engine) as db:
        run = db.get(EvaluationRun, run_id)
        run.status = status
        db.commit()
    monkeypatch.setattr(
        tasks, "get_settings", lambda: SimpleNamespace(evaluation_offline_enabled=False)
    )
    tasks.execute_evaluation.run(str(run_id))
    execute.assert_not_called()
    with Session(engine) as db:
        assert db.get(EvaluationRun, run_id).status == status
        assert db.get(EvaluationRun, run_id).error_code is None


@pytest.mark.parametrize("kind", ["missing", "live"])
def test_missing_or_live_evaluation_never_enters_offline_executor(worker_context, kind):
    engine, run_id, execute = worker_context
    if kind == "live":
        with Session(engine) as db:
            db.get(EvaluationRun, run_id).track = "live"
            db.commit()
    else:
        run_id = uuid.uuid4()
    tasks.execute_evaluation.run(str(run_id))
    execute.assert_not_called()


def test_evaluation_delegates_persisted_suite_and_owned_fixture(worker_context):
    from packages.evaluation.postgres_draft_adapter import postgres_case_factory

    engine, run_id, execute = worker_context
    tasks.execute_evaluation.run(str(run_id))
    execute.assert_called_once_with(
        engine, run_id, registered_suite("0.1.2"), postgres_case_factory
    )


@pytest.mark.parametrize(
    "failure,code",
    [
        (EvaluationLifecycleError("evaluation.runtime_changed"), "evaluation.runtime_changed"),
        (EvaluationLifecycleError("sensitive-fixture-detail"), "evaluation.suite_changed"),
        (ValueError("sensitive-fixture-detail"), "evaluation.suite_changed"),
    ],
)
def test_evaluation_freeze_failure_commits_only_safe_codes(worker_context, failure, code):
    engine, run_id, execute = worker_context
    execute.side_effect = failure
    tasks.execute_evaluation.run(str(run_id))
    with Session(engine) as db:
        run = db.get(EvaluationRun, run_id)
        case = db.scalar(select(EvaluationCaseResult))
        assert run is not None and case is not None
        assert run.status == "failed" and run.error_code == code
        assert case.status == "blocked" and case.error_code == code
        assert "sensitive" not in repr(run.summary)


def test_unexpected_executor_failure_propagates_instead_of_claiming_completion(worker_context):
    engine, run_id, execute = worker_context
    execute.side_effect = RuntimeError("synthetic failure")
    with pytest.raises(RuntimeError, match="synthetic failure"):
        tasks.execute_evaluation.run(str(run_id))
    with Session(engine) as db:
        assert db.get(EvaluationRun, run_id).status == "queued"
        assert db.scalar(select(EvaluationCaseResult.status)) == "queued"


def test_invalid_evaluation_identity_does_not_open_database(monkeypatch):
    engine = Mock(side_effect=AssertionError("database must not open"))
    monkeypatch.setattr(tasks, "get_engine", engine)
    with pytest.raises(ValueError):
        tasks.execute_evaluation.run("not-a-uuid")
    engine.assert_not_called()


def test_recovery_commits_stale_failure_and_preserves_passed_case(worker_context):
    engine, run_id, execute = worker_context
    with Session(engine) as db:
        run = db.get(EvaluationRun, run_id)
        run.status = "running"
        run.started_at = datetime.now(UTC) - timedelta(hours=1)
        db.add(
            EvaluationCaseResult(
                workspace_id=run.workspace_id,
                evaluation_run_id=run.id,
                case_id="already-passed",
                category="standard",
                status="passed",
                assertion_results=[{"name": "trusted_result", "passed": True}],
            )
        )
        db.commit()
    assert tasks.recover_stale_evaluations.run() == 1
    assert tasks.recover_stale_evaluations.run() == 0
    execute.assert_not_called()
    with Session(engine) as db:
        run = db.get(EvaluationRun, run_id)
        cases = {item.case_id: item for item in db.scalars(select(EvaluationCaseResult))}
        assert run.status == "partial" and run.error_code == "evaluation.worker_lost"
        assert cases["worker-fixture"].status == "infra_error"
        assert cases["already-passed"].status == "passed"
        assert cases["already-passed"].assertion_results == [
            {"name": "trusted_result", "passed": True}
        ]


def test_recovery_quarantines_uncertain_receipt_without_refund_or_resend(monkeypatch):
    db, run, engine = _live()
    run_id = run.id
    receipt_id = reserve_call(engine, run_id, "synthetic-worker-call", "a" * 64, 100)
    db.expire_all()
    receipt = db.get(EvaluationModelCall, receipt_id)
    receipt.created_at = datetime.now(UTC) - timedelta(minutes=6)
    db.commit()
    db.close()
    monkeypatch.setattr(tasks, "get_engine", lambda: engine)
    execute = Mock()
    monkeypatch.setattr(tasks, "execute_offline_run", execute)
    try:
        assert tasks.recover_stale_evaluations.run() == 1
        assert tasks.recover_stale_evaluations.run() == 0
        execute.assert_not_called()
        with Session(engine) as check:
            stored = check.get(EvaluationRun, run_id)
            assert stored.status == "partial" and stored.error_code == "evaluation.usage_uncertain"
            assert stored.calls_reserved == 1 and stored.tokens_reserved == 100
            assert stored.calls_used == stored.tokens_used == 0
            assert check.get(EvaluationModelCall, receipt_id).status == "usage_uncertain"
    finally:
        engine.dispose()
