import uuid

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from packages.agent_core.persistence import (
    AnalysisConversation,
    AnalysisConversationStatus,
    AnalysisReport,
    AnalysisReportFile,
    AnalysisReportFormat,
    AnalysisReportStatus,
)
from packages.platform_core.database import Base
from packages.platform_core.models import User, Workspace


def _database() -> tuple[Session, User, Workspace, AnalysisConversation]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
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
    db.commit()
    return db, user, workspace, conversation


def _report(
    user: User,
    workspace: Workspace,
    conversation: AnalysisConversation,
    *,
    idempotency_key: str = "report-1",
) -> AnalysisReport:
    return AnalysisReport(
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        created_by_user_id=user.id,
        idempotency_key=idempotency_key,
        title="第三季度质量分析报告",
        status=AnalysisReportStatus.QUEUED,
        template_key="quality-analysis",
        template_version="1.0.0",
        renderer_version="1.0.0",
        report_spec={"schema_version": 1, "sections": []},
        source_digest="a" * 64,
    )


def test_report_persists_three_generated_formats() -> None:
    db, user, workspace, conversation = _database()
    report = _report(user, workspace, conversation)
    db.add(report)
    db.flush()
    db.add_all(
        [
            AnalysisReportFile(
                workspace_id=workspace.id,
                report_id=report.id,
                format=format_value,
                object_key=f"reports/{workspace.id}/{report.id}/content.{extension}",
                media_type=media_type,
                byte_size=128,
                sha256_digest=digest * 64,
            )
            for format_value, extension, media_type, digest in (
                (AnalysisReportFormat.MARKDOWN, "md", "text/markdown", "b"),
                (AnalysisReportFormat.HTML, "html", "text/html", "c"),
                (AnalysisReportFormat.PDF, "pdf", "application/pdf", "d"),
            )
        ]
    )
    db.commit()

    assert report.status is AnalysisReportStatus.QUEUED
    assert {file.format for file in db.query(AnalysisReportFile).all()} == {
        AnalysisReportFormat.MARKDOWN,
        AnalysisReportFormat.HTML,
        AnalysisReportFormat.PDF,
    }


def test_report_idempotency_key_is_unique_per_workspace() -> None:
    db, user, workspace, conversation = _database()
    db.add_all(
        [
            _report(user, workspace, conversation),
            _report(user, workspace, conversation),
        ]
    )

    with pytest.raises(IntegrityError):
        db.commit()


def test_each_report_has_at_most_one_file_per_format() -> None:
    db, user, workspace, conversation = _database()
    report = _report(user, workspace, conversation)
    db.add(report)
    db.flush()
    db.add_all(
        [
            AnalysisReportFile(
                workspace_id=workspace.id,
                report_id=report.id,
                format=AnalysisReportFormat.PDF,
                object_key=f"reports/{report.id}/first.pdf",
                media_type="application/pdf",
                byte_size=10,
                sha256_digest="b" * 64,
            ),
            AnalysisReportFile(
                workspace_id=workspace.id,
                report_id=report.id,
                format=AnalysisReportFormat.PDF,
                object_key=f"reports/{report.id}/second.pdf",
                media_type="application/pdf",
                byte_size=10,
                sha256_digest="c" * 64,
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        db.commit()


def test_report_file_cannot_cross_workspace_boundary() -> None:
    db, user, workspace, conversation = _database()
    report = _report(user, workspace, conversation)
    other_workspace = Workspace(name="Other", slug=f"other-{uuid.uuid4().hex}")
    db.add_all([report, other_workspace])
    db.flush()
    db.add(
        AnalysisReportFile(
            workspace_id=other_workspace.id,
            report_id=report.id,
            format=AnalysisReportFormat.PDF,
            object_key=f"reports/{report.id}/content.pdf",
            media_type="application/pdf",
            byte_size=10,
            sha256_digest="b" * 64,
        )
    )

    with pytest.raises(IntegrityError):
        db.commit()
