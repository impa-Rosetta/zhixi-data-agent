import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, select
from test_evaluation_persistence import _database
from test_evaluation_runner import _suite

from packages.evaluation import ObservedOutcome
from packages.evaluation.execution import execute_offline_run
from packages.evaluation.lifecycle import (
    cancel_run,
    claim_case,
    claim_run,
    create_offline_run,
    finish_case,
    recover_offline_runs,
    resume_offline_run,
)
from packages.evaluation.persistence import EvaluationCaseResult
from packages.evaluation.runner import OfflineCaseExecution
from packages.evaluation.scoring import CaseScore


def _created():
    db, fixture = _database()
    suite = _suite()
    run = create_offline_run(
        db,
        workspace_id=fixture.workspace_id,
        actor_id=fixture.created_by_user_id,
        idempotency_key="execution",
        suite=suite,
    )
    db.commit()
    engine = db.get_bind()
    assert isinstance(engine, Engine)
    return db, run, suite, engine


def test_durable_execution_completes_and_duplicate_delivery_is_noop() -> None:
    db, run, suite, engine = _created()
    executed = []

    @contextmanager
    def factory(case):
        class Session:
            def execute(self):
                executed.append(case.id)
                return OfflineCaseExecution(ObservedOutcome(status="completed"))

        yield Session()

    execute_offline_run(engine, run.id, suite, factory)
    db.expire_all()
    assert run.status == "completed"
    assert run.summary["total"] == run.summary["passed"] == 3
    assert run.summary["coverage_rate"] == 1
    assert run.calls_used == run.tokens_used == 0
    execute_offline_run(engine, run.id, suite, factory)
    assert len(executed) == 3
    db.close()


def test_cleanup_failure_stops_remaining_cases_without_claiming_full_coverage() -> None:
    db, run, suite, engine = _created()

    @contextmanager
    def factory(case):
        class Session:
            def execute(self):
                return OfflineCaseExecution(ObservedOutcome(status="completed"))

        yield Session()
        raise OSError("sensitive cleanup details")

    execute_offline_run(engine, run.id, suite, factory)
    db.expire_all()
    assert run.status == "partial"
    assert run.summary["infra_error"] == 1 and run.summary["blocked"] == 2
    assert run.summary["coverage_rate"] == 0
    assert run.error_code == "evaluation.cleanup_failed"
    db.close()


def test_cancel_during_adapter_execution_fences_final_write() -> None:
    db, run, suite, engine = _created()

    @contextmanager
    def factory(case):
        class Session:
            def execute(self):
                cancel_run(db, run.workspace_id, run.id, run.created_by_user_id)
                db.commit()
                return OfflineCaseExecution(ObservedOutcome(status="completed"))

        yield Session()

    execute_offline_run(engine, run.id, suite, factory)
    db.expire_all()
    assert run.status == "cancelled"
    assert all(item.status == "blocked" for item in db.scalars(select(EvaluationCaseResult)))
    db.close()


def test_manual_recovery_resumes_only_unfinished_cases() -> None:
    db, run, suite, engine = _created()
    claim = claim_run(db, run.id, suite)
    assert claim is not None
    assert claim_case(db, claim, suite.cases[0].id) == 1
    assert finish_case(
        db, claim, CaseScore(suite.cases[0].id, "passed", ()), case_attempt=1, duration_ms=5
    )
    run.started_at = datetime.now(UTC) - timedelta(hours=1)
    db.commit()
    assert recover_offline_runs(db) == 1
    db.commit()
    resume_offline_run(db, run.workspace_id, run.id, run.created_by_user_id)
    db.commit()
    executed = []

    @contextmanager
    def factory(case):
        class Session:
            def execute(self):
                executed.append(case.id)
                return OfflineCaseExecution(ObservedOutcome(status="completed"))

        yield Session()

    execute_offline_run(engine, run.id, suite, factory)
    db.expire_all()
    assert run.status == "completed" and run.attempt_count == 2
    assert executed == [suite.cases[1].id, suite.cases[2].id]
    assert not finish_case(
        db, claim, CaseScore(suite.cases[1].id, "failed", ()), case_attempt=1, duration_ms=0
    )
    db.close()


def test_recovery_keeps_cross_case_reference_isolation() -> None:
    db, run, suite, engine = _created()
    claim = claim_run(db, run.id, suite)
    assert claim is not None
    reference = uuid.uuid4()
    assert claim_case(db, claim, suite.cases[0].id) == 1
    assert finish_case(
        db,
        claim,
        CaseScore(suite.cases[0].id, "passed", ()),
        case_attempt=1,
        duration_ms=1,
        run_references=(reference,),
    )
    run.started_at = datetime.now(UTC) - timedelta(hours=1)
    db.commit()
    assert recover_offline_runs(db) == 1
    db.commit()
    resume_offline_run(db, run.workspace_id, run.id, run.created_by_user_id)
    db.commit()

    @contextmanager
    def factory(case):
        class Session:
            def execute(self):
                return OfflineCaseExecution(ObservedOutcome(status="completed"), (reference,))

        yield Session()

    execute_offline_run(engine, run.id, suite, factory)
    db.expire_all()
    assert run.status == "partial"
    assert run.error_code == "evaluation.case_isolation_failed"
    assert run.summary["passed"] == 1 and run.summary["blocked"] == 2
    db.close()


def test_budget_overrun_on_final_case_is_not_reported_as_completed(monkeypatch) -> None:
    db, run, suite, engine = _created()
    clock = [0.0]
    monkeypatch.setattr("packages.evaluation.execution.time.monotonic", lambda: clock[0])

    @contextmanager
    def factory(case):
        class Session:
            def execute(self):
                if case.id == suite.cases[-1].id:
                    clock[0] = 301.0
                return OfflineCaseExecution(ObservedOutcome(status="completed"))

        yield Session()

    execute_offline_run(engine, run.id, suite, factory)
    db.expire_all()
    assert run.status == "partial" and run.error_code == "evaluation.budget_exceeded"
    assert run.summary["passed"] == 3
    db.close()
