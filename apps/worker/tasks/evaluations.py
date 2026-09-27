import uuid

from sqlalchemy.orm import Session

from apps.worker.celery_app import celery_app
from packages.evaluation.execution import execute_offline_run
from packages.evaluation.lifecycle import (
    EvaluationLifecycleError,
    fail_queued_run,
    recover_offline_runs,
)
from packages.evaluation.persistence import EvaluationRun
from packages.evaluation.registry import registered_suite
from packages.platform_core.database import get_engine
from packages.platform_core.settings import get_settings


@celery_app.task(name="evaluations.execute", acks_late=True)  # type: ignore[untyped-decorator]
def execute_evaluation(run_id: str) -> None:
    parsed = uuid.UUID(run_id)
    with Session(get_engine()) as db:
        if not get_settings().evaluation_offline_enabled:
            fail_queued_run(db, parsed, "evaluation.precondition_failed")
            db.commit()
            return
        run = db.get(EvaluationRun, parsed)
        if run is None or run.track != "offline":
            return
        version = run.suite_version
    from packages.evaluation.postgres_draft_adapter import postgres_case_factory

    try:
        execute_offline_run(get_engine(), parsed, registered_suite(version), postgres_case_factory)
    except (EvaluationLifecycleError, ValueError):
        with Session(get_engine()) as db:
            fail_queued_run(db, parsed, "evaluation.suite_changed")
            db.commit()


@celery_app.task(name="evaluations.recover_stale")  # type: ignore[untyped-decorator]
def recover_stale_evaluations() -> int:
    from packages.evaluation.model_budget import recover_uncertain_calls

    with Session(get_engine()) as db:
        recovered = recover_offline_runs(db)
        db.commit()
    return recovered + recover_uncertain_calls(get_engine())
