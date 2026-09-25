import hashlib
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.dependencies import get_current_user
from apps.api.main import app
from apps.api.routes import analysis_reports as report_routes
from apps.api.services.analysis_reports import (
    AnalysisReportServiceError,
    create_report,
    get_report,
    list_reports,
    read_report_file,
    retry_report,
)
from packages.agent_core.persistence import (
    AnalysisArtifact,
    AnalysisConversation,
    AnalysisConversationStatus,
    AnalysisEvidence,
    AnalysisReport,
    AnalysisReportFile,
    AnalysisReportFormat,
    AnalysisReportStatus,
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisTurn,
    AnalysisTurnRelation,
    AnalysisTurnStatus,
    AnalysisValidation,
)
from packages.platform_core.database import Base, get_db
from packages.platform_core.models import (
    AuditEvent,
    Membership,
    OutboxEvent,
    User,
    Workspace,
    WorkspaceRole,
)
from packages.shared_contracts.reports import CreateAnalysisReportRequest


def _trusted_source() -> tuple[
    Session,
    User,
    Workspace,
    AnalysisConversation,
    AnalysisTurn,
    AnalysisValidation,
]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = User(email="owner@example.com", display_name="Owner", password_hash="hash")
    workspace = Workspace(name="Factory", slug=f"factory-{uuid.uuid4().hex}")
    db.add_all([user, workspace])
    db.flush()
    conversation = AnalysisConversation(
        workspace_id=workspace.id,
        created_by_user_id=user.id,
        idempotency_key="conversation-1",
        title="质量分析",
        status=AnalysisConversationStatus.ACTIVE,
    )
    db.add(conversation)
    db.flush()
    turn = AnalysisTurn(
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        sequence=1,
        relation=AnalysisTurnRelation.INITIAL,
        status=AnalysisTurnStatus.COMPLETED,
    )
    db.add(turn)
    db.flush()
    run = AnalysisRun(
        workspace_id=workspace.id,
        created_by_user_id=user.id,
        conversation_id=conversation.id,
        turn_id=turn.id,
        idempotency_key="run-1",
        status=AnalysisRunStatus.COMPLETED,
    )
    db.add(run)
    db.flush()
    turn.analysis_run_id = run.id
    summary = {"columns": ["月份", "不良率"], "rows": [["9月", 2.4]]}
    digest = hashlib.sha256(
        json.dumps(
            summary,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    artifact = AnalysisArtifact(
        workspace_id=workspace.id,
        run_id=run.id,
        artifact_type="query_result",
        summary=summary,
        content_digest=digest,
    )
    db.add(artifact)
    db.flush()
    evidence = AnalysisEvidence(
        workspace_id=workspace.id,
        run_id=run.id,
        artifact_id=artifact.id,
        evidence_type="query_execution",
        reference={"trust": "trusted"},
        evidence_digest="b" * 64,
    )
    validation = AnalysisValidation(
        workspace_id=workspace.id,
        run_id=run.id,
        validation_type="evidence",
        outcome="passed",
        findings=[],
    )
    db.add_all([evidence, validation])
    db.commit()
    return db, user, workspace, conversation, turn, validation


def _payload(
    conversation: AnalysisConversation,
    turn: AnalysisTurn,
) -> CreateAnalysisReportRequest:
    return CreateAnalysisReportRequest(
        conversation_id=conversation.id,
        turn_ids=[turn.id],
        title="第三季度质量分析报告",
    )


def test_create_report_is_idempotent_and_records_delivery_intent() -> None:
    db, user, workspace, conversation, turn, _ = _trusted_source()
    payload = _payload(conversation, turn)

    first = create_report(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="report-create-1",
        payload=payload,
    )
    second = create_report(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="report-create-1",
        payload=payload,
    )
    db.commit()

    assert first.id == second.id
    assert first.status == "queued"
    assert first.spec.sections[0].source.evidence_ids
    assert db.scalar(select(func.count()).select_from(AnalysisReport)) == 1
    outbox = db.scalar(select(OutboxEvent))
    assert outbox is not None
    assert outbox.event_type == "analysis.report.requested"
    assert outbox.payload == {"report_id": str(first.id)}
    audit = db.scalar(select(AuditEvent).where(AuditEvent.action == "analysis_report.created"))
    assert audit is not None
    assert audit.resource_id == str(first.id)


def test_report_reads_are_workspace_scoped() -> None:
    db, user, workspace, conversation, turn, _ = _trusted_source()
    created = create_report(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="report-create-2",
        payload=_payload(conversation, turn),
    )
    db.commit()

    page = list_reports(db, workspace_id=workspace.id)
    assert page.total == 1
    assert page.items[0].id == created.id
    assert list_reports(db, workspace_id=workspace.id, conversation_id=conversation.id).total == 1
    assert list_reports(db, workspace_id=workspace.id, conversation_id=uuid.uuid4()).total == 0
    assert get_report(db, workspace_id=workspace.id, report_id=created.id).id == created.id

    other_workspace_id = uuid.uuid4()
    assert list_reports(db, workspace_id=other_workspace_id).total == 0
    with pytest.raises(AnalysisReportServiceError) as error:
        get_report(db, workspace_id=other_workspace_id, report_id=created.id)
    assert error.value.code == "analysis_report.not_found"


def test_report_creation_rejects_untrusted_validation() -> None:
    db, user, workspace, conversation, turn, validation = _trusted_source()
    validation.outcome = "failed"
    db.commit()

    with pytest.raises(AnalysisReportServiceError) as error:
        create_report(
            db,
            workspace_id=workspace.id,
            actor_user_id=user.id,
            idempotency_key="report-create-failed",
            payload=_payload(conversation, turn),
        )

    assert error.value.code == "report.validation_required"
    assert db.scalar(select(func.count()).select_from(AnalysisReport)) == 0


def test_report_routes_are_registered() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/workspaces/{workspace_id}/reports" in paths
    assert "/api/v1/workspaces/{workspace_id}/reports/{report_id}" in paths
    assert "/api/v1/workspaces/{workspace_id}/reports/{report_id}/preview" in paths
    assert "/api/v1/workspaces/{workspace_id}/reports/{report_id}/files/{format_value}" in paths
    assert "/api/v1/workspaces/{workspace_id}/reports/{report_id}/retry" in paths


class _FileStorage:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.calls = 0

    def get(self, object_key: str, *, max_bytes: int) -> bytes:
        assert object_key.endswith("/report.pdf")
        assert max_bytes >= len(self.content)
        self.calls += 1
        return self.content


def _generated_pdf() -> tuple[Session, User, Workspace, AnalysisReport, _FileStorage]:
    db, user, workspace, conversation, turn, _ = _trusted_source()
    created = create_report(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="report-download-1",
        payload=_payload(conversation, turn),
    )
    report = db.get(AnalysisReport, created.id)
    assert report is not None
    report.status = AnalysisReportStatus.SUCCEEDED
    content = b"%PDF-1.7\ntrusted\n"
    db.add(
        AnalysisReportFile(
            workspace_id=workspace.id,
            report_id=report.id,
            format=AnalysisReportFormat.PDF,
            object_key=f"reports/{workspace.id}/{report.id}/report.pdf",
            media_type="application/pdf",
            byte_size=len(content),
            sha256_digest=hashlib.sha256(content).hexdigest(),
        )
    )
    db.commit()
    return db, user, workspace, report, _FileStorage(content)


def test_report_download_verifies_digest_and_audits() -> None:
    db, user, workspace, report, storage = _generated_pdf()
    content, media_type, title = read_report_file(
        db,
        workspace_id=workspace.id,
        report_id=report.id,
        format_value=AnalysisReportFormat.PDF,
        storage=storage,
        actor_user_id=user.id,
    )
    assert content == storage.content
    assert media_type == "application/pdf"
    assert title == report.title
    assert db.scalar(select(AuditEvent).where(AuditEvent.action == "analysis_report.downloaded"))


def test_report_download_rejects_cross_workspace_before_storage_access() -> None:
    db, user, _, report, storage = _generated_pdf()
    with pytest.raises(AnalysisReportServiceError) as error:
        read_report_file(
            db,
            workspace_id=uuid.uuid4(),
            report_id=report.id,
            format_value=AnalysisReportFormat.PDF,
            storage=storage,
            actor_user_id=user.id,
        )
    assert error.value.code == "analysis_report.not_found"
    assert storage.calls == 0


def test_report_download_rejects_tampered_object() -> None:
    db, user, workspace, report, storage = _generated_pdf()
    storage.content = b"changed"
    with pytest.raises(AnalysisReportServiceError) as error:
        read_report_file(
            db,
            workspace_id=workspace.id,
            report_id=report.id,
            format_value=AnalysisReportFormat.PDF,
            storage=storage,
            actor_user_id=user.id,
        )
    assert error.value.code == "analysis_report.integrity_failed"
    assert (
        db.scalar(select(AuditEvent).where(AuditEvent.action == "analysis_report.downloaded"))
        is None
    )


def test_report_download_requires_completed_status() -> None:
    db, user, workspace, report, storage = _generated_pdf()
    report.status = AnalysisReportStatus.GENERATING
    db.commit()
    with pytest.raises(AnalysisReportServiceError) as error:
        read_report_file(
            db,
            workspace_id=workspace.id,
            report_id=report.id,
            format_value=AnalysisReportFormat.PDF,
            storage=storage,
            actor_user_id=user.id,
        )
    assert error.value.code == "analysis_report.not_ready"
    assert storage.calls == 0


def test_report_file_http_requires_membership_and_sets_safe_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, user, workspace, report, storage = _generated_pdf()
    db.add(Membership(user_id=user.id, workspace_id=workspace.id, role=WorkspaceRole.ANALYST))
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr(report_routes, "_storage", lambda: storage)
    url = f"/api/v1/workspaces/{workspace.id}/reports/{report.id}/files/pdf"
    try:
        with TestClient(app) as client:
            downloaded = client.get(url)
            assert downloaded.status_code == 200
            assert downloaded.content == storage.content
            assert downloaded.headers["content-disposition"].startswith("attachment;")
            assert downloaded.headers["cache-control"] == "private, no-store"
            assert "reports/" not in downloaded.text
            db.query(Membership).filter_by(user_id=user.id, workspace_id=workspace.id).delete()
            db.commit()
            assert client.get(url).status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_manual_retry_reuses_frozen_spec_and_emits_one_new_outbox_event() -> None:
    db, user, workspace, conversation, turn, _ = _trusted_source()
    created = create_report(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="report-retry-1",
        payload=_payload(conversation, turn),
    )
    report = db.get(AnalysisReport, created.id)
    assert report is not None
    original_digest = report.source_digest
    report.status = AnalysisReportStatus.FAILED
    report.error_code = "report.storage_unavailable"
    db.commit()

    retried = retry_report(
        db,
        workspace_id=workspace.id,
        report_id=report.id,
        actor_user_id=user.id,
    )
    db.commit()

    assert retried.status == "queued"
    assert retried.source_digest == original_digest
    assert retried.error_code is None
    assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 2
    audit = db.scalar(
        select(AuditEvent).where(AuditEvent.action == "analysis_report.retry_requested")
    )
    assert audit is not None
    assert audit.detail == "previous_error=report.storage_unavailable"
    with pytest.raises(AnalysisReportServiceError) as error:
        retry_report(
            db,
            workspace_id=workspace.id,
            report_id=report.id,
            actor_user_id=user.id,
        )
    assert error.value.code == "analysis_report.retry_not_allowed"


def test_manual_retry_rejects_permanent_failures() -> None:
    db, user, workspace, conversation, turn, _ = _trusted_source()
    created = create_report(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="report-retry-2",
        payload=_payload(conversation, turn),
    )
    report = db.get(AnalysisReport, created.id)
    assert report is not None
    report.status = AnalysisReportStatus.FAILED
    report.error_code = "report.spec_invalid"
    db.commit()

    with pytest.raises(AnalysisReportServiceError) as error:
        retry_report(
            db,
            workspace_id=workspace.id,
            report_id=report.id,
            actor_user_id=user.id,
        )

    assert error.value.code == "analysis_report.retry_not_allowed"
    assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 1
