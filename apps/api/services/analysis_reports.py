"""Transactional services for trusted report creation and retrieval."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from apps.api.audit import add_audit_event
from packages.agent_core.persistence import (
    AnalysisArtifact,
    AnalysisConversation,
    AnalysisEvidence,
    AnalysisReport,
    AnalysisReportFile,
    AnalysisReportFormat,
    AnalysisReportStatus,
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisTurn,
    AnalysisValidation,
)
from packages.platform_core.models import OutboxEvent
from packages.reporting import ReportCompositionError, compose_report_spec
from packages.shared_contracts.reports import (
    AnalysisReportPage,
    AnalysisReportResponse,
    CreateAnalysisReportRequest,
    ReportSpecV1,
)


class AnalysisReportServiceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


_RETRYABLE_REPORT_ERRORS = frozenset(
    {
        "report.storage_unavailable",
        "report.pdf_renderer_unavailable",
        "report.pdf_render_failed",
        "report.generation_unavailable",
        "report.worker_lost",
    }
)


class ReportFileStorage(Protocol):
    def get(self, object_key: str, *, max_bytes: int) -> bytes: ...


def read_report_file(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    report_id: uuid.UUID,
    format_value: AnalysisReportFormat,
    storage: ReportFileStorage,
    actor_user_id: uuid.UUID,
    preview: bool = False,
    max_bytes: int = 25 * 1024 * 1024,
) -> tuple[bytes, str, str]:
    """Read one private file and verify it before returning any bytes."""
    report = _get_report(db, workspace_id=workspace_id, report_id=report_id)
    if report.status is not AnalysisReportStatus.SUCCEEDED:
        raise AnalysisReportServiceError("analysis_report.not_ready", "Report is not ready")
    now = datetime.now(UTC)
    if report.expires_at is not None:
        expiry = (
            report.expires_at.replace(tzinfo=UTC)
            if report.expires_at.tzinfo is None
            else report.expires_at
        )
        if expiry <= now:
            raise AnalysisReportServiceError("analysis_report.expired", "Report has expired")
    report_file = db.scalar(
        select(AnalysisReportFile).where(
            AnalysisReportFile.workspace_id == workspace_id,
            AnalysisReportFile.report_id == report_id,
            AnalysisReportFile.format == format_value,
        )
    )
    if report_file is None:
        raise AnalysisReportServiceError("analysis_report.file_not_found", "Report file not found")
    if report_file.expires_at is not None:
        expiry = (
            report_file.expires_at.replace(tzinfo=UTC)
            if report_file.expires_at.tzinfo is None
            else report_file.expires_at
        )
        if expiry <= now:
            raise AnalysisReportServiceError("analysis_report.expired", "Report file has expired")
    if report_file.byte_size < 0 or report_file.byte_size > max_bytes:
        raise AnalysisReportServiceError(
            "analysis_report.file_too_large", "Report file unavailable"
        )
    try:
        content = storage.get(report_file.object_key, max_bytes=max_bytes)
    except Exception as exc:
        raise AnalysisReportServiceError(
            "analysis_report.storage_unavailable", "Report file unavailable"
        ) from exc
    if (
        len(content) != report_file.byte_size
        or hashlib.sha256(content).hexdigest() != report_file.sha256_digest
    ):
        raise AnalysisReportServiceError(
            "analysis_report.integrity_failed", "Report file failed integrity verification"
        )
    add_audit_event(
        db,
        action="analysis_report.previewed" if preview else "analysis_report.downloaded",
        outcome="success",
        resource_type="analysis_report",
        resource_id=str(report_id),
        actor_user_id=actor_user_id,
        workspace_id=workspace_id,
        detail=f"format={format_value.value}",
    )
    db.commit()
    return content, report_file.media_type, report.title


def _response(report: AnalysisReport) -> AnalysisReportResponse:
    return AnalysisReportResponse(
        id=report.id,
        workspace_id=report.workspace_id,
        conversation_id=report.conversation_id,
        created_by_user_id=report.created_by_user_id,
        title=report.title,
        status=report.status.value,
        template_key=report.template_key,
        template_version=report.template_version,
        renderer_version=report.renderer_version,
        spec=ReportSpecV1.model_validate(report.report_spec),
        source_digest=report.source_digest,
        content_digest=report.content_digest,
        error_code=report.error_code,
        attempt_count=report.attempt_count,
        expires_at=report.expires_at,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


def _get_report(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    report_id: uuid.UUID,
) -> AnalysisReport:
    report = db.scalar(
        select(AnalysisReport).where(
            AnalysisReport.id == report_id,
            AnalysisReport.workspace_id == workspace_id,
        )
    )
    if report is None:
        raise AnalysisReportServiceError("analysis_report.not_found", "Report not found")
    return report


def create_report(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    idempotency_key: str,
    payload: CreateAnalysisReportRequest,
) -> AnalysisReportResponse:
    existing = db.scalar(
        select(AnalysisReport).where(
            AnalysisReport.workspace_id == workspace_id,
            AnalysisReport.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return _response(existing)

    conversation = db.scalar(
        select(AnalysisConversation).where(
            AnalysisConversation.id == payload.conversation_id,
            AnalysisConversation.workspace_id == workspace_id,
        )
    )
    if conversation is None:
        raise AnalysisReportServiceError(
            "analysis_report.conversation_not_found",
            "Analysis conversation not found",
        )

    turns = list(
        db.scalars(
            select(AnalysisTurn).where(
                AnalysisTurn.workspace_id == workspace_id,
                AnalysisTurn.conversation_id == conversation.id,
                AnalysisTurn.id.in_(payload.turn_ids),
            )
        )
    )
    if len(turns) != len(payload.turn_ids):
        raise AnalysisReportServiceError(
            "analysis_report.turn_not_found",
            "One or more selected turns were not found",
        )
    run_ids = [turn.analysis_run_id for turn in turns if turn.analysis_run_id is not None]
    if len(run_ids) != len(turns):
        raise AnalysisReportServiceError(
            "analysis_report.turn_not_completed",
            "Every selected turn must have a completed analysis run",
        )
    runs = list(
        db.scalars(
            select(AnalysisRun).where(
                AnalysisRun.workspace_id == workspace_id,
                AnalysisRun.id.in_(run_ids),
            )
        )
    )
    if len(runs) != len(run_ids) or any(
        run.status is not AnalysisRunStatus.COMPLETED for run in runs
    ):
        raise AnalysisReportServiceError(
            "analysis_report.turn_not_completed",
            "Every selected turn must have a completed analysis run",
        )
    artifacts = list(
        db.scalars(
            select(AnalysisArtifact).where(
                AnalysisArtifact.workspace_id == workspace_id,
                AnalysisArtifact.run_id.in_(run_ids),
                AnalysisArtifact.artifact_type.in_(
                    ("query_result", "analysis_summary", "chart_spec")
                ),
            )
        )
    )
    artifact_ids = [artifact.id for artifact in artifacts]
    evidence = (
        list(
            db.scalars(
                select(AnalysisEvidence).where(
                    AnalysisEvidence.workspace_id == workspace_id,
                    AnalysisEvidence.artifact_id.in_(artifact_ids),
                )
            )
        )
        if artifact_ids
        else []
    )
    validations = list(
        db.scalars(
            select(AnalysisValidation).where(
                AnalysisValidation.workspace_id == workspace_id,
                AnalysisValidation.run_id.in_(run_ids),
            )
        )
    )
    try:
        composition = compose_report_spec(
            workspace_id=workspace_id,
            conversation_id=conversation.id,
            created_by_user_id=actor_user_id,
            title=payload.title,
            generated_at=datetime.now(UTC),
            runs=runs,
            turns=turns,
            artifacts=artifacts,
            evidence=evidence,
            validations=validations,
        )
    except ReportCompositionError as exc:
        raise AnalysisReportServiceError(
            exc.code, "Selected analysis results are not reportable"
        ) from exc

    report = AnalysisReport(
        workspace_id=workspace_id,
        conversation_id=conversation.id,
        created_by_user_id=actor_user_id,
        idempotency_key=idempotency_key,
        title=composition.spec.title,
        status=AnalysisReportStatus.QUEUED,
        template_key=composition.spec.template_key,
        template_version=composition.spec.template_version,
        renderer_version="1.0.0",
        report_spec=composition.spec.model_dump(mode="json"),
        source_digest=composition.source_digest,
    )
    db.add(report)
    db.flush()
    db.add(
        OutboxEvent(
            aggregate_type="analysis_report",
            aggregate_id=report.id,
            event_type="analysis.report.requested",
            payload={"report_id": str(report.id)},
        )
    )
    add_audit_event(
        db,
        action="analysis_report.created",
        outcome="success",
        resource_type="analysis_report",
        resource_id=str(report.id),
        actor_user_id=actor_user_id,
        workspace_id=workspace_id,
        detail=f"turns={len(turns)};template={report.template_key}",
    )
    db.flush()
    return _response(report)


def get_report(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    report_id: uuid.UUID,
) -> AnalysisReportResponse:
    return _response(_get_report(db, workspace_id=workspace_id, report_id=report_id))


def retry_report(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    report_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> AnalysisReportResponse:
    report = _get_report(db, workspace_id=workspace_id, report_id=report_id)
    if report.status is not AnalysisReportStatus.FAILED:
        raise AnalysisReportServiceError(
            "analysis_report.retry_not_allowed", "Only failed reports can be retried"
        )
    if report.error_code not in _RETRYABLE_REPORT_ERRORS:
        raise AnalysisReportServiceError(
            "analysis_report.retry_not_allowed", "This report cannot be retried"
        )
    previous_error = report.error_code
    claimed = db.execute(
        update(AnalysisReport)
        .where(
            AnalysisReport.id == report_id,
            AnalysisReport.workspace_id == workspace_id,
            AnalysisReport.status == AnalysisReportStatus.FAILED,
            AnalysisReport.error_code == previous_error,
        )
        .values(
            status=AnalysisReportStatus.QUEUED,
            error_code=None,
            started_at=None,
            finished_at=None,
        )
    )
    if getattr(claimed, "rowcount", 0) != 1:
        raise AnalysisReportServiceError(
            "analysis_report.retry_conflict", "Report state changed; refresh and try again"
        )
    db.add(
        OutboxEvent(
            aggregate_type="analysis_report",
            aggregate_id=report.id,
            event_type="analysis.report.requested",
            payload={"report_id": str(report.id)},
        )
    )
    add_audit_event(
        db,
        action="analysis_report.retry_requested",
        outcome="success",
        resource_type="analysis_report",
        resource_id=str(report.id),
        actor_user_id=actor_user_id,
        workspace_id=workspace_id,
        detail=f"previous_error={previous_error}",
    )
    db.flush()
    db.refresh(report)
    return _response(report)


def list_reports(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID | None = None,
    limit: int = 30,
    offset: int = 0,
) -> AnalysisReportPage:
    bounded_limit = max(1, min(limit, 100))
    bounded_offset = max(0, offset)
    filters = [AnalysisReport.workspace_id == workspace_id]
    if conversation_id is not None:
        filters.append(AnalysisReport.conversation_id == conversation_id)
    total = db.scalar(select(func.count()).select_from(AnalysisReport).where(*filters))
    reports = list(
        db.scalars(
            select(AnalysisReport)
            .where(*filters)
            .order_by(AnalysisReport.created_at.desc(), AnalysisReport.id.desc())
            .offset(bounded_offset)
            .limit(bounded_limit)
        )
    )
    return AnalysisReportPage(
        items=[_response(report) for report in reports],
        total=int(total or 0),
        limit=bounded_limit,
        offset=bounded_offset,
    )
