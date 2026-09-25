"""Idempotent report rendering and private object storage publishing."""

from __future__ import annotations

import hashlib
import io
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlparse

from minio import Minio
from pydantic import ValidationError
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from packages.agent_core.persistence import (
    AnalysisReport,
    AnalysisReportFile,
    AnalysisReportFormat,
    AnalysisReportStatus,
)
from packages.platform_core.models import AuditEvent, OutboxEvent
from packages.reporting import render_html, render_markdown
from packages.shared_contracts.reports import ReportSpecV1


class ReportGenerationError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class ReportObjectStorage(Protocol):
    def put(self, object_key: str, content: bytes, media_type: str) -> None: ...

    def delete(self, object_key: str) -> None: ...


PdfRenderer = Callable[[str], bytes]


@dataclass(frozen=True)
class GeneratedReportFile:
    format: AnalysisReportFormat
    extension: str
    media_type: str
    content: bytes
    sha256_digest: str


@dataclass(frozen=True)
class GeneratedReport:
    content_digest: str
    files: tuple[GeneratedReportFile, ...]


@dataclass(frozen=True)
class ReportClaim:
    spec: ReportSpecV1
    attempt_count: int


class MinioReportObjectStorage:
    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
    ) -> None:
        parsed = urlparse(endpoint_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("S3 endpoint must be an HTTP(S) URL")
        self._client = Minio(
            parsed.netloc,
            access_key=access_key,
            secret_key=secret_key,
            secure=parsed.scheme == "https",
        )
        self._bucket = bucket
        if not self._client.bucket_exists(bucket):
            self._client.make_bucket(bucket)

    def put(self, object_key: str, content: bytes, media_type: str) -> None:
        self._client.put_object(
            self._bucket,
            object_key,
            io.BytesIO(content),
            length=len(content),
            content_type=media_type,
        )

    def delete(self, object_key: str) -> None:
        self._client.remove_object(self._bucket, object_key)

    def get(self, object_key: str, *, max_bytes: int) -> bytes:
        response = self._client.get_object(self._bucket, object_key)
        try:
            content = response.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise ValueError("Report object exceeds download limit")
            return bytes(content)
        finally:
            response.close()
            response.release_conn()


def render_pdf(html_document: str) -> bytes:
    try:
        from weasyprint import HTML  # type: ignore[import-untyped]
        from weasyprint.urls import URLFetchingError  # type: ignore[import-untyped]
    except (ImportError, OSError) as exc:
        raise ReportGenerationError("report.pdf_renderer_unavailable", retryable=True) from exc

    def deny_external_url(url: str, *_: object, **__: object) -> object:
        raise URLFetchingError(f"External resource blocked: {url}")

    try:
        result = HTML(string=html_document, url_fetcher=deny_external_url).write_pdf()
    except Exception as exc:
        raise ReportGenerationError("report.pdf_render_failed", retryable=True) from exc
    return bytes(result)


def render_report(spec: ReportSpecV1, *, pdf_renderer: PdfRenderer = render_pdf) -> GeneratedReport:
    markdown = render_markdown(spec).encode("utf-8")
    html_document = render_html(spec)
    html_bytes = html_document.encode("utf-8")
    pdf = pdf_renderer(html_document)
    payloads = (
        (AnalysisReportFormat.MARKDOWN, "md", "text/markdown; charset=utf-8", markdown),
        (AnalysisReportFormat.HTML, "html", "text/html; charset=utf-8", html_bytes),
        (AnalysisReportFormat.PDF, "pdf", "application/pdf", pdf),
    )
    files = tuple(
        GeneratedReportFile(
            format=format_value,
            extension=extension,
            media_type=media_type,
            content=content,
            sha256_digest=hashlib.sha256(content).hexdigest(),
        )
        for format_value, extension, media_type, content in payloads
    )
    digest_source = "".join(f"{item.format.value}:{item.sha256_digest};" for item in files)
    return GeneratedReport(
        content_digest=hashlib.sha256(digest_source.encode("ascii")).hexdigest(),
        files=files,
    )


def claim_report(db: Session, report_id: uuid.UUID) -> ReportClaim | None:
    report = db.get(AnalysisReport, report_id)
    if report is None:
        raise ReportGenerationError("report.not_found", retryable=False)
    if report.status is AnalysisReportStatus.SUCCEEDED:
        return None
    if report.status is not AnalysisReportStatus.QUEUED:
        return None
    try:
        spec = ReportSpecV1.model_validate(report.report_spec)
    except ValidationError as exc:
        db.execute(
            update(AnalysisReport)
            .where(
                AnalysisReport.id == report_id,
                AnalysisReport.status == AnalysisReportStatus.QUEUED,
            )
            .values(
                status=AnalysisReportStatus.FAILED,
                error_code="report.spec_invalid",
                finished_at=datetime.now(UTC),
            )
        )
        db.commit()
        raise ReportGenerationError("report.spec_invalid", retryable=False) from exc
    claimed = db.execute(
        update(AnalysisReport)
        .where(
            AnalysisReport.id == report_id,
            AnalysisReport.status == AnalysisReportStatus.QUEUED,
        )
        .values(
            status=AnalysisReportStatus.GENERATING,
            attempt_count=AnalysisReport.attempt_count + 1,
            error_code=None,
            started_at=datetime.now(UTC),
        )
    )
    if getattr(claimed, "rowcount", 0) != 1:
        return None
    db.refresh(report)
    attempt_count = report.attempt_count
    db.commit()
    return ReportClaim(spec=spec, attempt_count=attempt_count)


def publish_report(
    db: Session,
    *,
    report_id: uuid.UUID,
    generated: GeneratedReport,
    storage: ReportObjectStorage,
    expected_attempt_count: int,
) -> None:
    report = db.get(AnalysisReport, report_id)
    if report is None:
        raise ReportGenerationError("report.not_found", retryable=False)
    if report.status is AnalysisReportStatus.SUCCEEDED:
        return
    if (
        report.status is not AnalysisReportStatus.GENERATING
        or report.attempt_count != expected_attempt_count
    ):
        raise ReportGenerationError("report.state_conflict", retryable=False)

    stored: list[tuple[GeneratedReportFile, str]] = []
    try:
        for item in generated.files:
            object_key = (
                f"reports/{report.workspace_id}/{report.id}/"
                f"attempt-{expected_attempt_count}/{generated.content_digest}.{item.extension}"
            )
            storage.put(object_key, item.content, item.media_type)
            stored.append((item, object_key))
    except Exception as exc:
        _delete_partial_objects(storage, stored)
        if isinstance(exc, ReportGenerationError):
            raise
        raise ReportGenerationError("report.storage_unavailable", retryable=True) from exc

    published = db.execute(
        update(AnalysisReport)
        .where(
            AnalysisReport.id == report.id,
            AnalysisReport.status == AnalysisReportStatus.GENERATING,
            AnalysisReport.attempt_count == expected_attempt_count,
        )
        .values(
            content_digest=generated.content_digest,
            status=AnalysisReportStatus.SUCCEEDED,
            error_code=None,
            finished_at=datetime.now(UTC),
        )
    )
    if getattr(published, "rowcount", 0) != 1:
        db.rollback()
        _delete_partial_objects(storage, stored)
        raise ReportGenerationError("report.state_conflict", retryable=False)
    db.execute(delete(AnalysisReportFile).where(AnalysisReportFile.report_id == report.id))
    for item, object_key in stored:
        db.add(
            AnalysisReportFile(
                workspace_id=report.workspace_id,
                report_id=report.id,
                format=item.format,
                object_key=object_key,
                media_type=item.media_type,
                byte_size=len(item.content),
                sha256_digest=item.sha256_digest,
            )
        )
    db.add(
        AuditEvent(
            workspace_id=report.workspace_id,
            actor_user_id=report.created_by_user_id,
            action="analysis_report.generated",
            resource_type="analysis_report",
            resource_id=str(report.id),
            outcome="success",
            detail=f"formats={len(stored)}",
        )
    )
    db.commit()


def reset_or_fail_report(
    db: Session,
    *,
    report_id: uuid.UUID,
    error_code: str,
    retrying: bool,
    expected_attempt_count: int,
) -> bool:
    report = db.get(AnalysisReport, report_id)
    if report is None:
        return False
    changed = db.execute(
        update(AnalysisReport)
        .where(
            AnalysisReport.id == report_id,
            AnalysisReport.status == AnalysisReportStatus.GENERATING,
            AnalysisReport.attempt_count == expected_attempt_count,
        )
        .values(
            status=AnalysisReportStatus.QUEUED if retrying else AnalysisReportStatus.FAILED,
            error_code=error_code,
            finished_at=None if retrying else datetime.now(UTC),
        )
    )
    if getattr(changed, "rowcount", 0) != 1:
        db.rollback()
        return False
    db.add(
        AuditEvent(
            workspace_id=report.workspace_id,
            actor_user_id=report.created_by_user_id,
            action="analysis_report.retry_scheduled" if retrying else "analysis_report.failed",
            resource_type="analysis_report",
            resource_id=str(report.id),
            outcome="retry" if retrying else "failure",
            detail=f"error_code={error_code}",
        )
    )
    db.commit()
    return True


def _delete_partial_objects(
    storage: ReportObjectStorage,
    stored: list[tuple[GeneratedReportFile, str]],
) -> None:
    for _, object_key in stored:
        # Storage outages must not hide the original failure. Attempt-scoped keys
        # prevent leftovers from colliding with a later successful retry.
        with suppress(Exception):
            storage.delete(object_key)


def recover_stale_reports(
    db: Session,
    *,
    now: datetime | None = None,
    max_age: timedelta = timedelta(minutes=15),
    batch_size: int = 100,
    max_attempts: int = 5,
) -> int:
    current_time = now or datetime.now(UTC)
    cutoff = current_time - max_age
    stale = list(
        db.scalars(
            select(AnalysisReport)
            .where(
                AnalysisReport.status == AnalysisReportStatus.GENERATING,
                AnalysisReport.started_at <= cutoff,
            )
            .order_by(AnalysisReport.started_at, AnalysisReport.id)
            .limit(batch_size)
        )
    )
    recovered = 0
    for report in stale:
        exhausted = report.attempt_count >= max_attempts
        changed = db.execute(
            update(AnalysisReport)
            .where(
                AnalysisReport.id == report.id,
                AnalysisReport.status == AnalysisReportStatus.GENERATING,
                AnalysisReport.attempt_count == report.attempt_count,
                AnalysisReport.started_at <= cutoff,
            )
            .values(
                status=AnalysisReportStatus.FAILED if exhausted else AnalysisReportStatus.QUEUED,
                error_code="report.worker_lost",
                started_at=None if not exhausted else report.started_at,
                finished_at=current_time if exhausted else None,
            )
            .execution_options(synchronize_session=False)
        )
        if getattr(changed, "rowcount", 0) != 1:
            continue
        if not exhausted:
            db.add(
                OutboxEvent(
                    aggregate_type="analysis_report",
                    aggregate_id=report.id,
                    event_type="analysis.report.requested",
                    payload={"report_id": str(report.id)},
                )
            )
        db.add(
            AuditEvent(
                workspace_id=report.workspace_id,
                actor_user_id=None,
                action="analysis_report.recovery_exhausted"
                if exhausted
                else "analysis_report.recovered",
                resource_type="analysis_report",
                resource_id=str(report.id),
                outcome="failure" if exhausted else "retry",
                detail=f"attempt={report.attempt_count}",
            )
        )
        recovered += 1
    db.commit()
    return recovered
