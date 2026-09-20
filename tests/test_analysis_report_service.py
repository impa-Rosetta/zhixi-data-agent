import hashlib
import json
import uuid

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.main import app
from apps.api.services.analysis_reports import (
    AnalysisReportServiceError,
    create_report,
    get_report,
    list_reports,
)
from packages.agent_core.persistence import (
    AnalysisArtifact,
    AnalysisConversation,
    AnalysisConversationStatus,
    AnalysisEvidence,
    AnalysisReport,
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisTurn,
    AnalysisTurnRelation,
    AnalysisTurnStatus,
    AnalysisValidation,
)
from packages.platform_core.database import Base
from packages.platform_core.models import AuditEvent, OutboxEvent, User, Workspace
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
