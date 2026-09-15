import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.services.analysis_conversations import (
    AnalysisConversationServiceError,
    create_conversation,
    get_conversation,
    list_conversations,
)
from apps.api.services.analysis_runs import create_run
from packages.agent_core.persistence import (
    AnalysisConversation,
    AnalysisEvent,
    AnalysisMessage,
    AnalysisRun,
    AnalysisTurn,
    AnalysisTurnRelation,
    AnalysisTurnStatus,
)
from packages.platform_core.database import Base
from packages.platform_core.models import OutboxEvent, User, Workspace
from packages.shared_contracts.agents import (
    CreateAnalysisConversationRequest,
    CreateAnalysisRunRequest,
)


def _database() -> tuple[Session, User, Workspace]:
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
    return db, user, workspace


def test_create_conversation_atomically_creates_first_turn_and_worker_run() -> None:
    db, user, workspace = _database()
    response = create_conversation(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="conversation-create-1",
        payload=CreateAnalysisConversationRequest(message="  本月\n不良率是多少？  "),
    )
    db.commit()

    conversation = db.get(AnalysisConversation, response.id)
    turn = db.scalar(
        select(AnalysisTurn).where(AnalysisTurn.conversation_id == response.id)
    )
    assert conversation is not None
    assert response.title == "本月 不良率是多少？"
    assert response.context.topic_summary == response.title
    assert turn is not None
    assert turn.sequence == 1
    assert turn.relation is AnalysisTurnRelation.INITIAL
    assert turn.status is AnalysisTurnStatus.QUEUED
    assert turn.analysis_run_id is not None
    run = db.get(AnalysisRun, turn.analysis_run_id)
    assert run is not None
    assert run.conversation_id == conversation.id
    assert run.turn_id == turn.id
    assert conversation.active_turn_id == turn.id
    assert conversation.last_turn_sequence == 1
    assert db.scalar(select(func.count()).select_from(AnalysisMessage)) == 1
    assert db.scalar(select(func.count()).select_from(AnalysisEvent)) == 1
    outbox = db.scalar(select(OutboxEvent))
    assert outbox is not None
    assert outbox.aggregate_id == run.id
    assert outbox.event_type == "analysis.run.requested"


def test_create_conversation_is_idempotent_inside_workspace() -> None:
    db, user, workspace = _database()
    payload = CreateAnalysisConversationRequest(message="本月不良率是多少？")

    first = create_conversation(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="same-create",
        payload=payload,
    )
    second = create_conversation(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="same-create",
        payload=payload,
    )

    assert second.id == first.id
    assert db.scalar(select(func.count()).select_from(AnalysisConversation)) == 1
    assert db.scalar(select(func.count()).select_from(AnalysisTurn)) == 1
    assert db.scalar(select(func.count()).select_from(AnalysisRun)) == 1
    assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 1


def test_conversation_listing_is_recent_first_and_workspace_isolated() -> None:
    db, user, workspace = _database()
    older = create_conversation(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="older",
        payload=CreateAnalysisConversationRequest(message="旧问题"),
    )
    older_record = db.get(AnalysisConversation, older.id)
    assert older_record is not None
    older_record.updated_at = datetime.now(UTC) - timedelta(days=1)
    newer = create_conversation(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="newer",
        payload=CreateAnalysisConversationRequest(message="新问题"),
    )
    other_workspace = Workspace(name="Other", slug=f"other-{uuid.uuid4().hex}")
    db.add(other_workspace)
    db.flush()
    create_conversation(
        db,
        workspace_id=other_workspace.id,
        actor_user_id=user.id,
        idempotency_key="other",
        payload=CreateAnalysisConversationRequest(message="其他空间问题"),
    )
    db.commit()

    page = list_conversations(db, workspace_id=workspace.id, limit=20, offset=0)

    assert page.total == 2
    assert [item.id for item in page.items] == [newer.id, older.id]
    assert page.items[0].active_turn_status == "queued"
    assert page.items[0].last_message_preview == "新问题"
    with pytest.raises(AnalysisConversationServiceError) as error:
        get_conversation(
            db,
            workspace_id=other_workspace.id,
            conversation_id=newer.id,
        )
    assert error.value.code == "analysis_conversation.not_found"


def test_legacy_create_run_remains_unlinked() -> None:
    db, user, workspace = _database()

    result = create_run(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="legacy-create",
        payload=CreateAnalysisRunRequest(message="旧入口仍然可用"),
    )
    stored = db.get(AnalysisRun, result.id)

    assert stored is not None
    assert stored.conversation_id is None
    assert stored.turn_id is None
