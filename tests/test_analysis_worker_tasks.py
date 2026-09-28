from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session
from test_analysis_conversation_service import _database

from apps.api.services.analysis_conversations import create_conversation, send_conversation_message
from apps.worker.tasks import analysis_runs as tasks
from packages.agent_core.persistence import (
    AnalysisConversation,
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisTurn,
    AnalysisTurnStatus,
)
from packages.platform_core.models import OutboxEvent
from packages.shared_contracts.agents import (
    CreateAnalysisConversationRequest,
    SendAnalysisConversationMessageRequest,
)


@pytest.fixture
def worker_context(monkeypatch):
    db, user, workspace = _database()
    conversation = create_conversation(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="synthetic-worker",
        payload=CreateAnalysisConversationRequest(message="你好"),
    )
    db.commit()
    turn = db.scalar(select(AnalysisTurn))
    run_id, turn_id, conversation_id = turn.analysis_run_id, turn.id, conversation.id
    engine = db.get_bind()
    assert isinstance(engine, Engine)
    db.close()
    gateway = object()
    constructor = Mock(return_value=gateway)
    monkeypatch.setattr(tasks, "DeepSeekGateway", constructor)
    monkeypatch.setattr(tasks, "get_engine", lambda: engine)
    monkeypatch.setattr(
        tasks,
        "get_settings",
        lambda: SimpleNamespace(
            deepseek_api_key=SecretStr("synthetic-not-a-secret"),
            deepseek_base_url="https://example.invalid",
            deepseek_model="synthetic-model",
            deepseek_timeout_seconds=7.0,
            deepseek_max_attempts=1,
        ),
    )
    try:
        yield engine, run_id, turn_id, conversation_id, gateway, constructor
    finally:
        engine.dispose()


def test_analysis_worker_wires_gateway_and_commits_run_and_conversation(
    worker_context, monkeypatch
):
    engine, run_id, turn_id, conversation_id, gateway, constructor = worker_context
    sessions = []

    def complete(db, *, run_id, gateway):
        sessions.append(db)
        stored = db.get(AnalysisRun, run_id)
        stored.status = AnalysisRunStatus.COMPLETED
        stored.finished_at = datetime.now(UTC)

    runner = Mock(side_effect=complete)
    synchronize = tasks.synchronize_conversation_after_run
    sync = Mock(wraps=synchronize)
    monkeypatch.setattr(tasks, "run_analysis", runner)
    monkeypatch.setattr(tasks, "synchronize_conversation_after_run", sync)
    tasks.execute_analysis_run.run(str(run_id))
    constructor.assert_called_once_with(
        api_key="synthetic-not-a-secret",
        base_url="https://example.invalid",
        model="synthetic-model",
        timeout_seconds=7.0,
        max_attempts=1,
    )
    runner.assert_called_once_with(sessions[0], run_id=run_id, gateway=gateway)
    sync.assert_called_once_with(sessions[0], run_id=run_id)
    with Session(engine) as db:
        assert db.get(AnalysisRun, run_id).status is AnalysisRunStatus.COMPLETED
        assert db.get(AnalysisTurn, turn_id).status is AnalysisTurnStatus.COMPLETED
        assert db.get(AnalysisConversation, conversation_id).active_turn_id is None


@pytest.mark.parametrize("stage", ["analysis", "synchronization", "commit"])
def test_analysis_worker_rolls_back_both_stages_on_failure(worker_context, monkeypatch, stage):
    engine, run_id, turn_id, conversation_id, _, _ = worker_context

    def execute(db, *, run_id, gateway):
        stored = db.get(AnalysisRun, run_id)
        stored.status = AnalysisRunStatus.COMPLETED
        db.flush()
        if stage == "analysis":
            raise RuntimeError("synthetic analysis failure")

    original_sync = tasks.synchronize_conversation_after_run

    def synchronize(db, *, run_id):
        original_sync(db, run_id=run_id)
        db.flush()
        if stage == "synchronization":
            raise RuntimeError("synthetic synchronization failure")

    if stage == "commit":

        class FailingCommitSession(Session):
            def commit(self):
                self.flush()
                raise RuntimeError("synthetic commit failure")

        monkeypatch.setattr(tasks, "Session", FailingCommitSession)

    sync = Mock(side_effect=synchronize)
    monkeypatch.setattr(tasks, "run_analysis", execute)
    monkeypatch.setattr(tasks, "synchronize_conversation_after_run", sync)
    with pytest.raises(RuntimeError, match=f"synthetic {stage} failure"):
        tasks.execute_analysis_run.run(str(run_id))
    assert sync.call_count == (0 if stage == "analysis" else 1)
    with Session(engine) as db:
        assert db.get(AnalysisRun, run_id).status is AnalysisRunStatus.QUEUED
        assert db.get(AnalysisTurn, turn_id).status is AnalysisTurnStatus.QUEUED
        assert db.get(AnalysisConversation, conversation_id).active_turn_id == turn_id


def test_invalid_analysis_identity_never_runs_domain_or_sync(worker_context, monkeypatch):
    runner, sync = Mock(), Mock()
    monkeypatch.setattr(tasks, "run_analysis", runner)
    monkeypatch.setattr(tasks, "synchronize_conversation_after_run", sync)
    with pytest.raises(ValueError):
        tasks.execute_analysis_run.run("not-a-uuid")
    runner.assert_not_called()
    sync.assert_not_called()


def test_analysis_worker_atomically_activates_next_queued_turn(worker_context, monkeypatch):
    engine, run_id, turn_id, conversation_id, _, _ = worker_context
    with Session(engine) as db:
        run = db.get(AnalysisRun, run_id)
        run.status = AnalysisRunStatus.RUNNING
        db.get(AnalysisTurn, turn_id).status = AnalysisTurnStatus.RUNNING
        send_conversation_message(
            db,
            workspace_id=run.workspace_id,
            conversation_id=conversation_id,
            actor_user_id=run.created_by_user_id,
            idempotency_key="synthetic-follow-up",
            payload=SendAnalysisConversationMessageRequest(message="有哪些数据源？"),
        )
        db.commit()
        next_turn = db.scalar(select(AnalysisTurn).where(AnalysisTurn.sequence == 2))
        next_turn_id, next_run_id = next_turn.id, next_turn.analysis_run_id
        assert db.get(AnalysisConversation, conversation_id).active_turn_id == turn_id
        assert len(list(db.scalars(select(OutboxEvent)))) == 1

    def complete(db, *, run_id, gateway):
        run = db.get(AnalysisRun, run_id)
        run.status = AnalysisRunStatus.COMPLETED
        run.finished_at = datetime.now(UTC)

    monkeypatch.setattr(tasks, "run_analysis", complete)
    tasks.execute_analysis_run.run(str(run_id))
    with Session(engine) as db:
        assert db.get(AnalysisTurn, turn_id).status is AnalysisTurnStatus.COMPLETED
        assert db.get(AnalysisTurn, next_turn_id).status is AnalysisTurnStatus.QUEUED
        assert db.get(AnalysisConversation, conversation_id).active_turn_id == next_turn_id
        events = list(
            db.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id == next_run_id))
        )
        assert len(events) == 1
        assert events[0].event_type == "analysis.run.requested"
        assert events[0].payload == {"run_id": str(next_run_id)}
