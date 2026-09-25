import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from packages.agent_core.persistence import (
    AnalysisConversation,
    AnalysisConversationStatus,
    AnalysisReport,
    AnalysisReportFile,
    AnalysisReportStatus,
)
from packages.platform_core.database import Base
from packages.platform_core.models import AuditEvent, OutboxEvent, User, Workspace
from packages.reporting.generation import (
    ReportGenerationError,
    claim_report,
    cleanup_orphaned_report_objects,
    publish_report,
    recover_stale_reports,
    render_report,
    reset_or_fail_report,
)
from packages.shared_contracts.reports import (
    ReportSection,
    ReportSourceRef,
    ReportSpecV1,
)


class MemoryStorage:
    def __init__(self, *, fail: bool = False, fail_on_put: int | None = None) -> None:
        self.fail = fail
        self.fail_on_put = fail_on_put
        self.put_count = 0
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, object_key: str, content: bytes, media_type: str) -> None:
        self.put_count += 1
        if self.fail or self.put_count == self.fail_on_put:
            raise OSError("storage unavailable")
        self.objects[object_key] = (content, media_type)

    def delete(self, object_key: str) -> None:
        self.objects.pop(object_key, None)

    def list_older_than(self, cutoff: datetime) -> list[str]:
        del cutoff
        return list(self.objects)


def _database() -> tuple[Session, AnalysisReport]:
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
    source = ReportSourceRef(
        turn_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        artifact_id=uuid.uuid4(),
        artifact_type="query_result",
        content_digest="a" * 64,
        evidence_ids=[uuid.uuid4()],
        validation_ids=[uuid.uuid4()],
    )
    spec = ReportSpecV1(
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        created_by_user_id=user.id,
        generated_at="2026-09-20T12:00:00Z",
        title="质量分析报告",
        sections=[
            ReportSection(
                kind="data",
                title="可信查询结果",
                summary={"columns": ["月份", "不良率"], "rows": [["9月", 2.4]]},
                source=source,
            )
        ],
    )
    report = AnalysisReport(
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        created_by_user_id=user.id,
        idempotency_key="report-1",
        title=spec.title,
        status=AnalysisReportStatus.QUEUED,
        template_key=spec.template_key,
        template_version=spec.template_version,
        renderer_version="1.0.0",
        report_spec=spec.model_dump(mode="json"),
        source_digest="b" * 64,
    )
    db.add(report)
    db.commit()
    return db, report


def test_render_report_produces_three_hashed_formats() -> None:
    db, report = _database()
    spec = ReportSpecV1.model_validate(report.report_spec)

    generated = render_report(
        spec,
        pdf_renderer=lambda html: ("%PDF-1.7\n" + html).encode("utf-8"),
    )

    assert [item.extension for item in generated.files] == ["md", "html", "pdf"]
    assert all(len(item.sha256_digest) == 64 for item in generated.files)
    assert len(generated.content_digest) == 64
    db.close()


def test_claim_and_publish_are_idempotent() -> None:
    db, report = _database()
    claim = claim_report(db, report.id)
    assert claim is not None
    assert db.get(AnalysisReport, report.id).status is AnalysisReportStatus.GENERATING
    assert claim_report(db, report.id) is None

    generated = render_report(claim.spec, pdf_renderer=lambda _: b"%PDF-1.7")
    storage = MemoryStorage()
    publish_report(
        db,
        report_id=report.id,
        generated=generated,
        storage=storage,
        expected_attempt_count=claim.attempt_count,
    )
    publish_report(
        db,
        report_id=report.id,
        generated=generated,
        storage=storage,
        expected_attempt_count=claim.attempt_count,
    )

    stored = db.get(AnalysisReport, report.id)
    assert stored is not None and stored.status is AnalysisReportStatus.SUCCEEDED
    assert stored.attempt_count == 1
    assert len(storage.objects) == 3
    assert len(list(db.scalars(select(AnalysisReportFile)))) == 3
    assert db.scalar(select(AuditEvent).where(AuditEvent.action == "analysis_report.generated"))


def test_storage_failure_can_be_requeued_then_failed() -> None:
    db, report = _database()
    claim = claim_report(db, report.id)
    assert claim is not None
    generated = render_report(claim.spec, pdf_renderer=lambda _: b"%PDF-1.7")

    with pytest.raises(ReportGenerationError) as error:
        publish_report(
            db,
            report_id=report.id,
            generated=generated,
            storage=MemoryStorage(fail=True),
            expected_attempt_count=claim.attempt_count,
        )
    assert error.value.retryable

    reset_or_fail_report(
        db,
        report_id=report.id,
        error_code=error.value.code,
        retrying=True,
        expected_attempt_count=claim.attempt_count,
    )
    assert db.get(AnalysisReport, report.id).status is AnalysisReportStatus.QUEUED
    second_claim = claim_report(db, report.id)
    assert second_claim is not None
    reset_or_fail_report(
        db,
        report_id=report.id,
        error_code=error.value.code,
        retrying=False,
        expected_attempt_count=second_claim.attempt_count,
    )
    stored = db.get(AnalysisReport, report.id)
    assert stored is not None and stored.status is AnalysisReportStatus.FAILED
    assert stored.finished_at is not None


def test_partial_upload_is_removed_before_retry() -> None:
    db, report = _database()
    claim = claim_report(db, report.id)
    assert claim is not None
    generated = render_report(claim.spec, pdf_renderer=lambda _: b"%PDF-1.7")
    storage = MemoryStorage(fail_on_put=2)

    with pytest.raises(ReportGenerationError, match="report.storage_unavailable"):
        publish_report(
            db,
            report_id=report.id,
            generated=generated,
            storage=storage,
            expected_attempt_count=claim.attempt_count,
        )
    assert storage.objects == {}
    assert db.get(AnalysisReport, report.id).status is AnalysisReportStatus.GENERATING


def test_recovery_requeues_stale_generation_and_fences_old_worker() -> None:
    db, report = _database()
    first = claim_report(db, report.id)
    assert first is not None
    report.started_at = datetime(2026, 9, 1, tzinfo=UTC)
    db.commit()

    assert recover_stale_reports(db, now=datetime(2026, 9, 2, tzinfo=UTC)) == 1
    db.refresh(report)
    assert report.status is AnalysisReportStatus.QUEUED
    assert report.error_code == "report.worker_lost"
    assert db.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == report.id))

    second = claim_report(db, report.id)
    assert second is not None and second.attempt_count == first.attempt_count + 1
    reset_or_fail_report(
        db,
        report_id=report.id,
        error_code="report.storage_unavailable",
        retrying=False,
        expected_attempt_count=first.attempt_count,
    )
    db.refresh(report)
    assert report.status is AnalysisReportStatus.GENERATING
    generated = render_report(first.spec, pdf_renderer=lambda _: b"%PDF-1.7")
    with pytest.raises(ReportGenerationError, match="report.state_conflict"):
        publish_report(
            db,
            report_id=report.id,
            generated=generated,
            storage=MemoryStorage(),
            expected_attempt_count=first.attempt_count,
        )
    publish_report(
        db,
        report_id=report.id,
        generated=generated,
        storage=MemoryStorage(),
        expected_attempt_count=second.attempt_count,
    )
    db.refresh(report)
    assert report.status is AnalysisReportStatus.SUCCEEDED


def test_recovery_ignores_fresh_work_and_fails_exhausted_attempts() -> None:
    db, report = _database()
    claim = claim_report(db, report.id)
    assert claim is not None
    assert recover_stale_reports(db, now=datetime.now(UTC), max_age=timedelta(hours=1)) == 0
    report.started_at = datetime(2026, 9, 1, tzinfo=UTC)
    report.attempt_count = 5
    db.commit()

    assert recover_stale_reports(db, now=datetime(2026, 9, 2, tzinfo=UTC)) == 1
    db.refresh(report)
    assert report.status is AnalysisReportStatus.FAILED
    assert report.error_code == "report.worker_lost"
    assert not list(db.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id == report.id)))


def test_cleanup_removes_only_unreferenced_old_attempt_objects() -> None:
    db, report = _database()
    claim = claim_report(db, report.id)
    assert claim is not None
    generated = render_report(claim.spec, pdf_renderer=lambda _: b"%PDF-1.7")
    storage = MemoryStorage()
    publish_report(
        db,
        report_id=report.id,
        generated=generated,
        storage=storage,
        expected_attempt_count=claim.attempt_count,
    )
    legitimate_keys = set(storage.objects)
    orphan_key = f"reports/{report.workspace_id}/{report.id}/attempt-0/orphan.pdf"
    storage.put(orphan_key, b"orphan", "application/pdf")
    malformed_key = "reports/not-a-workspace/not-a-report/attempt-0/bad.pdf"
    storage.put(malformed_key, b"bad", "application/pdf")

    report.status = AnalysisReportStatus.GENERATING
    db.commit()
    assert cleanup_orphaned_report_objects(db, storage) == 0
    report.status = AnalysisReportStatus.SUCCEEDED
    db.commit()
    assert cleanup_orphaned_report_objects(db, storage) == 1
    assert set(storage.objects) == legitimate_keys | {malformed_key}
