"""Idempotent report rendering and private object storage publishing."""

from __future__ import annotations

import hashlib
import io
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlparse

from minio import Minio
from pydantic import ValidationError
from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from packages.agent_core.persistence import (
    AnalysisReport,
    AnalysisReportFile,
    AnalysisReportFormat,
    AnalysisReportStatus,
)
from packages.platform_core.models import AuditEvent
from packages.reporting import render_html, render_markdown
from packages.shared_contracts.reports import ReportSpecV1


class ReportGenerationError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class ReportObjectStorage(Protocol):
    def put(self, object_key: str, content: bytes, media_type: str) -> None: ...


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


def claim_report(db: Session, report_id: uuid.UUID) -> ReportSpecV1 | None:
    report = db.get(AnalysisReport, report_id)
    if report is None:
        raise ReportGenerationError("report.not_found", retryable=False)
    if report.status is AnalysisReportStatus.SUCCEEDED:
        return None
    if report.status is not AnalysisReportStatus.QUEUED:
        return None
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
    try:
        spec = ReportSpecV1.model_validate(report.report_spec)
    except ValidationError as exc:
        raise ReportGenerationError("report.spec_invalid", retryable=False) from exc
    db.commit()
    return spec


def publish_report(
    db: Session,
    *,
    report_id: uuid.UUID,
    generated: GeneratedReport,
    storage: ReportObjectStorage,
) -> None:
    report = db.get(AnalysisReport, report_id)
    if report is None:
        raise ReportGenerationError("report.not_found", retryable=False)
    if report.status is AnalysisReportStatus.SUCCEEDED:
        return
    if report.status is not AnalysisReportStatus.GENERATING:
        raise ReportGenerationError("report.state_conflict", retryable=False)

    stored: list[tuple[GeneratedReportFile, str]] = []
    try:
        for item in generated.files:
            object_key = (
                f"reports/{report.workspace_id}/{report.id}/"
                f"{generated.content_digest}.{item.extension}"
            )
            storage.put(object_key, item.content, item.media_type)
            stored.append((item, object_key))
    except Exception as exc:
        if isinstance(exc, ReportGenerationError):
            raise
        raise ReportGenerationError("report.storage_unavailable", retryable=True) from exc

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
    report.content_digest = generated.content_digest
    report.status = AnalysisReportStatus.SUCCEEDED
    report.error_code = None
    report.finished_at = datetime.now(UTC)
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
) -> None:
    report = db.get(AnalysisReport, report_id)
    if report is None or report.status is AnalysisReportStatus.SUCCEEDED:
        return
    report.status = AnalysisReportStatus.QUEUED if retrying else AnalysisReportStatus.FAILED
    report.error_code = error_code
    if not retrying:
        report.finished_at = datetime.now(UTC)
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
