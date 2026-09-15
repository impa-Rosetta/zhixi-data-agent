import uuid

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from packages.agent_core.persistence import (
    AnalysisConversation,
    AnalysisConversationStatus,
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisTurn,
    AnalysisTurnRelation,
    AnalysisTurnStatus,
)
from packages.platform_core.database import Base
from packages.platform_core.models import User, Workspace


def _database() -> tuple[Session, User, Workspace]:
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
    return db, user, workspace


def _conversation(db: Session, user: User, workspace: Workspace) -> AnalysisConversation:
    conversation = AnalysisConversation(
        workspace_id=workspace.id,
        created_by_user_id=user.id,
        idempotency_key="conversation-1",
        title="查看本月不良率",
        status=AnalysisConversationStatus.ACTIVE,
    )
    db.add(conversation)
    db.flush()
    return conversation


def test_conversation_turn_and_run_can_be_linked_without_rewriting_legacy_runs() -> None:
    db, user, workspace = _database()
    conversation = _conversation(db, user, workspace)
    turn = AnalysisTurn(
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        sequence=1,
        relation=AnalysisTurnRelation.INITIAL,
        status=AnalysisTurnStatus.QUEUED,
    )
    db.add(turn)
    db.flush()
    run = AnalysisRun(
        workspace_id=workspace.id,
        created_by_user_id=user.id,
        idempotency_key="run-1",
        status=AnalysisRunStatus.QUEUED,
        conversation_id=conversation.id,
        turn_id=turn.id,
    )
    legacy_run = AnalysisRun(
        workspace_id=workspace.id,
        created_by_user_id=user.id,
        idempotency_key="legacy-run",
        status=AnalysisRunStatus.QUEUED,
    )
    db.add_all([run, legacy_run])
    db.flush()
    turn.analysis_run_id = run.id
    conversation.active_turn_id = turn.id
    conversation.last_turn_sequence = 1
    db.commit()

    stored_turn = db.scalar(select(AnalysisTurn).where(AnalysisTurn.id == turn.id))
    stored_legacy = db.scalar(select(AnalysisRun).where(AnalysisRun.id == legacy_run.id))

    assert stored_turn is not None
    assert stored_turn.analysis_run_id == run.id
    assert conversation.active_turn_id == turn.id
    assert stored_legacy is not None
    assert stored_legacy.conversation_id is None
    assert stored_legacy.turn_id is None


def test_turn_sequence_is_unique_inside_a_conversation() -> None:
    db, user, workspace = _database()
    conversation = _conversation(db, user, workspace)
    db.add_all(
        [
            AnalysisTurn(
                workspace_id=workspace.id,
                conversation_id=conversation.id,
                sequence=1,
                relation=AnalysisTurnRelation.INITIAL,
                status=AnalysisTurnStatus.QUEUED,
            ),
            AnalysisTurn(
                workspace_id=workspace.id,
                conversation_id=conversation.id,
                sequence=1,
                relation=AnalysisTurnRelation.CONTINUE,
                status=AnalysisTurnStatus.QUEUED,
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        db.commit()


def test_each_turn_and_run_form_a_one_to_one_pair() -> None:
    db, user, workspace = _database()
    conversation = _conversation(db, user, workspace)
    turn = AnalysisTurn(
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        sequence=1,
        relation=AnalysisTurnRelation.INITIAL,
        status=AnalysisTurnStatus.QUEUED,
    )
    db.add(turn)
    db.flush()
    db.add_all(
        [
            AnalysisRun(
                workspace_id=workspace.id,
                created_by_user_id=user.id,
                idempotency_key="run-1",
                status=AnalysisRunStatus.QUEUED,
                conversation_id=conversation.id,
                turn_id=turn.id,
            ),
            AnalysisRun(
                workspace_id=workspace.id,
                created_by_user_id=user.id,
                idempotency_key="run-2",
                status=AnalysisRunStatus.QUEUED,
                conversation_id=conversation.id,
                turn_id=turn.id,
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        db.commit()


def test_turn_cannot_reference_a_conversation_from_another_workspace() -> None:
    db, user, workspace = _database()
    conversation = _conversation(db, user, workspace)
    other_workspace = Workspace(name="Other", slug=f"other-{uuid.uuid4().hex}")
    db.add(other_workspace)
    db.flush()
    db.add(
        AnalysisTurn(
            workspace_id=other_workspace.id,
            conversation_id=conversation.id,
            sequence=1,
            relation=AnalysisTurnRelation.INITIAL,
            status=AnalysisTurnStatus.QUEUED,
        )
    )

    with pytest.raises(IntegrityError):
        db.commit()
