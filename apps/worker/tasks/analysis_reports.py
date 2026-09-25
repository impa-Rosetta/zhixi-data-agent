"""Celery tasks for trusted report generation."""

from __future__ import annotations

import uuid

from celery import Task  # type: ignore[import-untyped]
from sqlalchemy.orm import Session

from apps.worker.celery_app import celery_app
from packages.platform_core.database import get_engine
from packages.platform_core.settings import get_settings
from packages.reporting.generation import (
    MinioReportObjectStorage,
    ReportGenerationError,
    claim_report,
    cleanup_orphaned_report_objects,
    publish_report,
    recover_stale_reports,
    render_report,
    reset_or_fail_report,
)


def _storage() -> MinioReportObjectStorage:
    settings = get_settings()
    return MinioReportObjectStorage(
        endpoint_url=settings.s3_endpoint_url,
        access_key=settings.s3_access_key.get_secret_value(),
        secret_key=settings.s3_secret_key.get_secret_value(),
        bucket=settings.s3_bucket,
    )


@celery_app.task(
    bind=True,
    name="analysis_reports.generate",
    acks_late=True,
    max_retries=2,
)  # type: ignore[untyped-decorator]
def generate_analysis_report(task: Task, report_id: str) -> None:
    parsed_report_id = uuid.UUID(report_id)
    claim = None
    try:
        with Session(get_engine()) as db:
            claim = claim_report(db, parsed_report_id)
        if claim is None:
            return
        generated = render_report(claim.spec)
        with Session(get_engine()) as db:
            publish_report(
                db,
                report_id=parsed_report_id,
                generated=generated,
                storage=_storage(),
                expected_attempt_count=claim.attempt_count,
            )
    except Exception as caught:
        exc = (
            caught
            if isinstance(caught, ReportGenerationError)
            else ReportGenerationError("report.generation_unavailable", retryable=True)
        )
        retrying = exc.retryable and task.request.retries < task.max_retries
        state_changed = False
        if claim is not None:
            with Session(get_engine()) as db:
                state_changed = reset_or_fail_report(
                    db,
                    report_id=parsed_report_id,
                    error_code=exc.code,
                    retrying=retrying,
                    expected_attempt_count=claim.attempt_count,
                )
        if retrying and state_changed:
            raise task.retry(exc=exc, countdown=2 ** (task.request.retries + 1)) from exc


@celery_app.task(name="analysis_reports.recover_stale")  # type: ignore[untyped-decorator]
def recover_stale_analysis_reports() -> int:
    with Session(get_engine()) as db:
        return recover_stale_reports(db)


@celery_app.task(name="analysis_reports.cleanup_orphans")  # type: ignore[untyped-decorator]
def cleanup_orphaned_analysis_report_objects() -> int:
    with Session(get_engine()) as db:
        return cleanup_orphaned_report_objects(db, _storage())
