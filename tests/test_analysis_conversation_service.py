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
    get_conversation_view,
    list_conversations,
    send_conversation_message,
)
from apps.api.services.analysis_runs import create_run
from packages.agent_core.conversation_runtime import synchronize_conversation_after_run
from packages.agent_core.persistence import (
    AnalysisConversation,
    AnalysisEvent,
    AnalysisMessage,
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisTurn,
    AnalysisTurnRelation,
    AnalysisTurnStatus,
)
from packages.platform_core.database import Base
from packages.platform_core.models import OutboxEvent, User, Workspace
from packages.shared_contracts.agents import (
    CreateAnalysisConversationRequest,
    CreateAnalysisRunRequest,
    SendAnalysisConversationMessageRequest,
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


def test_completed_run_can_continue_in_same_conversation() -> None:
    db, user, workspace = _database()
    conversation = create_conversation(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="continue-conversation",
        payload=CreateAnalysisConversationRequest(message="不良率是多少？"),
    )
    first_turn = db.scalar(select(AnalysisTurn).where(AnalysisTurn.sequence == 1))
    assert first_turn is not None and first_turn.analysis_run_id is not None
    first_run = db.get(AnalysisRun, first_turn.analysis_run_id)
    assert first_run is not None
    first_run.status = AnalysisRunStatus.COMPLETED
    first_run.finished_at = datetime.now(UTC)
    synchronize_conversation_after_run(db, run_id=first_run.id)

    send_conversation_message(
        db,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        actor_user_id=user.id,
        idempotency_key="follow-up-1",
        payload=SendAnalysisConversationMessageRequest(message="按月份展开"),
    )
    db.commit()
    view = get_conversation_view(
        db,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
    )

    assert view.total_turns == 2
    assert [item.turn.sequence for item in view.turns] == [1, 2]
    assert view.turns[0].turn.status == "completed"
    assert view.turns[1].analysis.messages[0].content == "按月份展开"
    assert view.conversation.active_turn_id == view.turns[1].turn.id
    assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 2


def test_messages_sent_while_running_queue_and_activate_strictly_in_order() -> None:
    db, user, workspace = _database()
    conversation = create_conversation(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="queued-conversation",
        payload=CreateAnalysisConversationRequest(message="先分析不良率"),
    )
    first_turn = db.scalar(select(AnalysisTurn).where(AnalysisTurn.sequence == 1))
    assert first_turn is not None and first_turn.analysis_run_id is not None
    first_run = db.get(AnalysisRun, first_turn.analysis_run_id)
    assert first_run is not None
    first_run.status = AnalysisRunStatus.RUNNING
    first_turn.status = AnalysisTurnStatus.RUNNING

    for key, message in (("queued-2", "然后按月"), ("queued-3", "再找最高月份")):
        send_conversation_message(
            db,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            actor_user_id=user.id,
            idempotency_key=key,
            payload=SendAnalysisConversationMessageRequest(message=message),
        )
    db.flush()
    stored_conversation = db.get(AnalysisConversation, conversation.id)
    assert stored_conversation is not None
    assert stored_conversation.active_turn_id == first_turn.id
    assert db.scalar(select(func.count()).select_from(AnalysisTurn)) == 3
    assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 1

    first_run.status = AnalysisRunStatus.COMPLETED
    first_run.finished_at = datetime.now(UTC)
    assert synchronize_conversation_after_run(db, run_id=first_run.id)
    second_turn = db.scalar(select(AnalysisTurn).where(AnalysisTurn.sequence == 2))
    assert second_turn is not None and second_turn.analysis_run_id is not None
    assert stored_conversation.active_turn_id == second_turn.id
    assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 2

    assert not synchronize_conversation_after_run(db, run_id=first_run.id)
    assert stored_conversation.active_turn_id == second_turn.id
    assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 2

    second_run = db.get(AnalysisRun, second_turn.analysis_run_id)
    assert second_run is not None
    second_run.status = AnalysisRunStatus.COMPLETED
    second_run.finished_at = datetime.now(UTC)
    assert synchronize_conversation_after_run(db, run_id=second_run.id)
    third_turn = db.scalar(select(AnalysisTurn).where(AnalysisTurn.sequence == 3))
    assert third_turn is not None
    assert stored_conversation.active_turn_id == third_turn.id
    assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 3


def test_clarification_reply_reuses_current_turn_and_run() -> None:
    db, user, workspace = _database()
    conversation = create_conversation(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="clarification-conversation",
        payload=CreateAnalysisConversationRequest(message="看看这个比例"),
    )
    turn = db.scalar(select(AnalysisTurn))
    assert turn is not None and turn.analysis_run_id is not None
    run = db.get(AnalysisRun, turn.analysis_run_id)
    assert run is not None
    run.status = AnalysisRunStatus.WAITING_FOR_CLARIFICATION

    send_conversation_message(
        db,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        actor_user_id=user.id,
        idempotency_key="clarification-answer",
        payload=SendAnalysisConversationMessageRequest(message="分析不良率"),
    )

    assert db.scalar(select(func.count()).select_from(AnalysisTurn)) == 1
    assert db.scalar(select(func.count()).select_from(AnalysisRun)) == 1
    assert db.scalar(select(func.count()).select_from(AnalysisMessage)) == 2
    assert run.status is AnalysisRunStatus.QUEUED
