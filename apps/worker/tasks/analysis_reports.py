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
    publish_report,
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
    try:
        with Session(get_engine()) as db:
            spec = claim_report(db, parsed_report_id)
        if spec is None:
            return
        generated = render_report(spec)
        with Session(get_engine()) as db:
            publish_report(
                db,
                report_id=parsed_report_id,
                generated=generated,
                storage=_storage(),
            )
    except Exception as caught:
        exc = (
            caught
            if isinstance(caught, ReportGenerationError)
            else ReportGenerationError("report.generation_unavailable", retryable=True)
        )
        retrying = exc.retryable and task.request.retries < task.max_retries
        with Session(get_engine()) as db:
            reset_or_fail_report(
                db,
                report_id=parsed_report_id,
                error_code=exc.code,
                retrying=retrying,
            )
        if retrying:
            raise task.retry(exc=exc, countdown=2 ** (task.request.retries + 1)) from exc
