import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.services.analysis_conversations import (
    AnalysisConversationServiceError,
    cancel_conversation_turn,
    create_conversation,
    get_conversation,
    get_conversation_view,
    list_conversations,
    send_conversation_message,
)
from apps.api.services.analysis_runs import add_event, create_run
from packages.agent_core.conversation_events import (
    list_conversation_events,
    stream_conversation_events,
)
from packages.agent_core.conversation_runtime import (
    recover_conversation_queues,
    synchronize_conversation_after_run,
)
from packages.agent_core.persistence import (
    AnalysisArtifact,
    AnalysisConversation,
    AnalysisEvent,
    AnalysisEvidence,
    AnalysisMessage,
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisTurn,
    AnalysisTurnRelation,
    AnalysisTurnStatus,
    AnalysisValidation,
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


def test_run_events_are_projected_to_replayable_conversation_events() -> None:
    db, user, workspace = _database()
    response = create_conversation(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="conversation-events",
        payload=CreateAnalysisConversationRequest(message="分析本月不良率"),
    )
    turn = db.scalar(select(AnalysisTurn).where(AnalysisTurn.conversation_id == response.id))
    assert turn is not None and turn.analysis_run_id is not None
    run = db.get(AnalysisRun, turn.analysis_run_id)
    assert run is not None
    add_event(db, run, "run.node", {"node": "understand"})
    db.commit()

    events = list_conversation_events(
        db,
        workspace_id=workspace.id,
        conversation_id=response.id,
    )
    assert [event.event_type for event in events] == ["run.created", "run.node"]
    assert [event.sequence for event in events] == [1, 2]
    assert events[1].turn_id == turn.id
    assert events[1].run_id == run.id
    assert events[1].turn_sequence == 1
    assert events[1].run_event_sequence == 2

    stream = stream_conversation_events(
        db,
        workspace_id=workspace.id,
        conversation_id=response.id,
        after=1,
        poll_interval_seconds=0.01,
        heartbeat_seconds=60,
    )

    async def read_one() -> str:
        item = await anext(stream)
        await stream.aclose()
        return item

    frame = asyncio.run(read_one())
    assert "id: 2" in frame
    assert "event: run.node" in frame
    assert '"turn_sequence":1' in frame


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
    latest_window = get_conversation_view(
        db,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        limit=1,
    )
    assert [item.turn.sequence for item in latest_window.turns] == [2]


def test_completed_run_updates_safe_context_and_queued_turn_uses_latest_snapshot() -> None:
    db, user, workspace = _database()
    conversation = create_conversation(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="context-conversation",
        payload=CreateAnalysisConversationRequest(message="分析不良率"),
    )
    first_turn = db.scalar(select(AnalysisTurn).where(AnalysisTurn.sequence == 1))
    assert first_turn is not None and first_turn.analysis_run_id is not None
    first_run = db.get(AnalysisRun, first_turn.analysis_run_id)
    assert first_run is not None
    first_run.context = {
        **first_run.context,
        "intent": {
            "domain": "manufacturing_quality",
            "task_type": "metric_query",
            "goal": "分析不良率",
            "metrics": ["不良率"],
            "dimensions": [],
            "filters": {},
            "time_range": None,
            "comparison": None,
            "output": ["table"],
            "ambiguities": [],
            "confidence": 1.0,
        },
        "binding": {
            "semantic_model_id": str(uuid.uuid4()),
            "semantic_version_id": str(uuid.uuid4()),
            "snapshot_ids": [str(uuid.uuid4())],
            "metric_keys": ["defect_rate"],
            "dimension_keys": [],
            "confidence": 1.0,
        },
        "result": {"rows": [[0.03]], "row_count": 1},
        "connection_string": "must-not-be-inherited",
    }
    artifact = AnalysisArtifact(
        workspace_id=workspace.id,
        run_id=first_run.id,
        artifact_type="query_result",
        summary={"row_count": 1},
        content_digest="a" * 64,
    )
    db.add(artifact)
    db.flush()
    evidence = AnalysisEvidence(
        workspace_id=workspace.id,
        run_id=first_run.id,
        artifact_id=artifact.id,
        evidence_type="query_execution",
        reference={"trust": "trusted"},
        evidence_digest="b" * 64,
    )
    db.add(evidence)
    db.add(
        AnalysisValidation(
            workspace_id=workspace.id,
            run_id=first_run.id,
            validation_type="result_contract",
            outcome="passed",
            findings=[],
        )
    )
    first_run.status = AnalysisRunStatus.RUNNING
    first_turn.status = AnalysisTurnStatus.RUNNING
    send_conversation_message(
        db,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        actor_user_id=user.id,
        idempotency_key="queued-refine",
        payload=SendAnalysisConversationMessageRequest(message="按月份展开"),
    )

    first_run.status = AnalysisRunStatus.COMPLETED
    first_run.finished_at = datetime.now(UTC)
    assert synchronize_conversation_after_run(db, run_id=first_run.id)

    stored = db.get(AnalysisConversation, conversation.id)
    second_turn = db.scalar(select(AnalysisTurn).where(AnalysisTurn.sequence == 2))
    assert stored is not None
    assert second_turn is not None and second_turn.analysis_run_id is not None
    second_run = db.get(AnalysisRun, second_turn.analysis_run_id)
    assert second_run is not None
    assert stored.context["metric"] == {"key": "defect_rate", "name": "不良率"}
    assert stored.context["last_result"]["artifact_id"] == str(artifact.id)
    assert stored.context["last_result"]["evidence_id"] == str(evidence.id)
    assert "connection_string" not in stored.context
    assert second_turn.context_before == stored.context
    assert second_run.context["conversation_context"] == stored.context


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


def test_recovery_activates_a_queued_successor_after_worker_commit_gap() -> None:
    db, user, workspace = _database()
    conversation = create_conversation(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="recovery-conversation",
        payload=CreateAnalysisConversationRequest(message="先分析不良率"),
    )
    first_turn = db.scalar(select(AnalysisTurn).where(AnalysisTurn.sequence == 1))
    assert first_turn is not None and first_turn.analysis_run_id is not None
    first_run = db.get(AnalysisRun, first_turn.analysis_run_id)
    assert first_run is not None
    first_run.status = AnalysisRunStatus.RUNNING
    first_turn.status = AnalysisTurnStatus.RUNNING
    send_conversation_message(
        db,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        actor_user_id=user.id,
        idempotency_key="queued-after-gap",
        payload=SendAnalysisConversationMessageRequest(message="再按月份展开"),
    )
    first_run.status = AnalysisRunStatus.COMPLETED
    first_run.finished_at = datetime.now(UTC)
    db.commit()

    assert recover_conversation_queues(db) == 1
    db.commit()

    stored = db.get(AnalysisConversation, conversation.id)
    second_turn = db.scalar(select(AnalysisTurn).where(AnalysisTurn.sequence == 2))
    assert stored is not None and second_turn is not None
    assert stored.active_turn_id == second_turn.id
    requested = db.scalars(
        select(OutboxEvent).where(OutboxEvent.event_type == "analysis.run.requested")
    ).all()
    assert len(requested) == 2
    assert recover_conversation_queues(db) == 0
    assert len(db.scalars(select(OutboxEvent)).all()) == 2


def test_recovery_repairs_missing_active_turn_without_duplicate_outbox() -> None:
    db, user, workspace = _database()
    conversation = create_conversation(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="recovery-no-active",
        payload=CreateAnalysisConversationRequest(message="分析不良率"),
    )
    stored = db.get(AnalysisConversation, conversation.id)
    assert stored is not None
    stored.active_turn_id = None
    db.commit()

    assert recover_conversation_queues(db) == 1
    db.commit()
    turn = db.scalar(select(AnalysisTurn).where(AnalysisTurn.conversation_id == conversation.id))
    assert turn is not None
    assert stored.active_turn_id == turn.id
    assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 1


def test_cancelling_active_turn_preserves_and_activates_queued_successor() -> None:
    db, user, workspace = _database()
    conversation = create_conversation(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="cancel-with-queue",
        payload=CreateAnalysisConversationRequest(message="执行较长分析"),
    )
    first_turn = db.scalar(select(AnalysisTurn).where(AnalysisTurn.sequence == 1))
    assert first_turn is not None and first_turn.analysis_run_id is not None
    first_run = db.get(AnalysisRun, first_turn.analysis_run_id)
    assert first_run is not None
    first_run.status = AnalysisRunStatus.RUNNING
    first_turn.status = AnalysisTurnStatus.RUNNING
    send_conversation_message(
        db,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        actor_user_id=user.id,
        idempotency_key="after-cancel",
        payload=SendAnalysisConversationMessageRequest(message="改看数据库有哪些表"),
    )

    result = cancel_conversation_turn(
        db,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        turn_id=first_turn.id,
        actor_user_id=user.id,
    )
    second_turn = db.scalar(select(AnalysisTurn).where(AnalysisTurn.sequence == 2))
    assert second_turn is not None
    assert first_run.status is AnalysisRunStatus.CANCELLED
    assert first_turn.status is AnalysisTurnStatus.CANCELLED
    assert result.active_turn_id == second_turn.id
    assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 2


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
