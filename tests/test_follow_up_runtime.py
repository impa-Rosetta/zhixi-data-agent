import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.services.analysis_conversations import (
    create_conversation,
    send_conversation_message,
)
from apps.worker.analysis_runtime import run_analysis
from packages.agent_core.conversation_runtime import synchronize_conversation_after_run
from packages.agent_core.persistence import (
    AnalysisArtifact,
    AnalysisEvidence,
    AnalysisMessage,
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisToolCall,
    AnalysisTurn,
    AnalysisTurnRelation,
    AnalysisValidation,
)
from packages.model_gateway import FakeGateway, GatewayResponse, GatewayUsage
from packages.platform_core.database import Base
from packages.platform_core.models import User, Workspace
from packages.shared_contracts.agents import (
    CreateAnalysisConversationRequest,
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


def _completed_first_turn(
    db: Session,
    user: User,
    workspace: Workspace,
) -> tuple[uuid.UUID, AnalysisRun, AnalysisArtifact]:
    conversation = create_conversation(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="follow-up-runtime",
        payload=CreateAnalysisConversationRequest(message="分析本月不良率"),
    )
    turn = db.scalar(select(AnalysisTurn).where(AnalysisTurn.sequence == 1))
    assert turn is not None and turn.analysis_run_id is not None
    run = db.get(AnalysisRun, turn.analysis_run_id)
    assert run is not None
    run.context = {
        **run.context,
        "intent": {
            "domain": "manufacturing_quality",
            "task_type": "metric_query",
            "goal": "分析本月不良率",
            "metrics": ["不良率"],
            "dimensions": [],
            "filters": {},
            "time_range": "本月",
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
        "result": {"columns": ["defect_rate"], "rows": [[0.03]], "row_count": 1},
    }
    artifact = AnalysisArtifact(
        workspace_id=workspace.id,
        run_id=run.id,
        artifact_type="query_result",
        summary={"row_count": 1},
        content_digest="a" * 64,
    )
    db.add(artifact)
    db.flush()
    db.add(
        AnalysisEvidence(
            workspace_id=workspace.id,
            run_id=run.id,
            artifact_id=artifact.id,
            evidence_type="query_execution",
            reference={"trust": "trusted"},
            evidence_digest="b" * 64,
        )
    )
    db.add(
        AnalysisValidation(
            workspace_id=workspace.id,
            run_id=run.id,
            validation_type="result_contract",
            outcome="passed",
            findings=[],
        )
    )
    run.status = AnalysisRunStatus.COMPLETED
    run.finished_at = datetime.now(UTC)
    synchronize_conversation_after_run(db, run_id=run.id)
    db.commit()
    return conversation.id, run, artifact


def _send_follow_up(
    db: Session,
    user: User,
    workspace: Workspace,
    conversation_id: uuid.UUID,
    *,
    key: str,
    message: str,
) -> tuple[AnalysisTurn, AnalysisRun]:
    send_conversation_message(
        db,
        workspace_id=workspace.id,
        conversation_id=conversation_id,
        actor_user_id=user.id,
        idempotency_key=key,
        payload=SendAnalysisConversationMessageRequest(message=message),
    )
    turn = db.scalar(select(AnalysisTurn).where(AnalysisTurn.sequence == 2))
    assert turn is not None and turn.analysis_run_id is not None
    run = db.get(AnalysisRun, turn.analysis_run_id)
    assert run is not None
    return turn, run


def test_refine_follow_up_inherits_previous_intent_before_binding() -> None:
    db, user, workspace = _database()
    conversation_id, _, _ = _completed_first_turn(db, user, workspace)
    turn, run = _send_follow_up(
        db,
        user,
        workspace,
        conversation_id,
        key="refine-follow-up",
        message="按月份展开",
    )
    gateway = FakeGateway(
        [
            GatewayResponse(
                "revision-1",
                "fake",
                json.dumps(
                    {
                        "mode": "patch",
                        "patch": {
                            "metrics": None,
                            "dimensions": ["月份"],
                            "filters": None,
                            "time_range": None,
                            "comparison": None,
                            "output": ["time_series"],
                        },
                        "replacement": None,
                    },
                    ensure_ascii=False,
                ),
                None,
                (),
                "stop",
                GatewayUsage(20, 10, 30),
            )
        ]
    )

    run_analysis(db, run_id=run.id, gateway=gateway)
    synchronize_conversation_after_run(db, run_id=run.id)
    db.refresh(run)
    db.refresh(turn)

    assert turn.relation is AnalysisTurnRelation.REFINE
    assert run.context["intent"]["metrics"] == ["不良率"]
    assert run.context["intent"]["dimensions"] == ["月份"]
    assert run.context["intent"]["output"] == ["time_series"]
    assert run.context["follow_up_relation"] == "refine"
    assert run.model_calls == 1
    assert len(gateway.calls) == 1


def test_explain_follow_up_reuses_verified_result_without_querying_source() -> None:
    db, user, workspace = _database()
    conversation_id, first_run, source_artifact = _completed_first_turn(db, user, workspace)
    turn, run = _send_follow_up(
        db,
        user,
        workspace,
        conversation_id,
        key="explain-follow-up",
        message="为什么会这样？",
    )
    gateway = FakeGateway([])

    run_analysis(db, run_id=run.id, gateway=gateway)
    db.refresh(run)
    db.refresh(turn)

    assert run.status is AnalysisRunStatus.COMPLETED
    assert turn.relation is AnalysisTurnRelation.EXPLAIN
    assert gateway.calls == []
    tool_call = db.scalar(select(AnalysisToolCall).where(AnalysisToolCall.run_id == run.id))
    assert tool_call is not None
    assert tool_call.tool_name == "analysis.describe"
    assert tool_call.result_summary["source_artifact_id"] == str(source_artifact.id)
    conversation_context = db.scalar(
        select(AnalysisTurn.context_after).where(AnalysisTurn.id == turn.id)
    )
    assert conversation_context["last_result"]["artifact_id"] == str(source_artifact.id)
    message = db.scalar(
        select(AnalysisMessage)
        .where(AnalysisMessage.run_id == run.id, AnalysisMessage.role == "assistant")
        .order_by(AnalysisMessage.created_at.desc())
    )
    assert message is not None
    assert "仅凭汇总结果不能可靠判断原因" in message.content
    assert db.get(AnalysisRun, first_run.id) is not None


def test_ambiguous_follow_up_asks_naturally_in_the_same_turn() -> None:
    db, user, workspace = _database()
    conversation_id, _, _ = _completed_first_turn(db, user, workspace)
    turn, run = _send_follow_up(
        db,
        user,
        workspace,
        conversation_id,
        key="ambiguous-follow-up",
        message="换一种方式看看",
    )
    gateway = FakeGateway(
        [
            GatewayResponse(
                "classification-1",
                "fake",
                json.dumps(
                    {
                        "relation": "refine",
                        "patch": None,
                        "needs_clarification": True,
                        "clarification_question": (
                            "你是想调整上一轮的展示方式，还是开始分析新的指标？"
                        ),
                        "confidence": 0.45,
                    },
                    ensure_ascii=False,
                ),
                None,
                (),
                "stop",
                GatewayUsage(20, 10, 30),
            )
        ]
    )

    run_analysis(db, run_id=run.id, gateway=gateway)
    db.refresh(run)

    assert run.status is AnalysisRunStatus.WAITING_FOR_CLARIFICATION
    assert turn.relation is AnalysisTurnRelation.REFINE
    message = db.scalar(
        select(AnalysisMessage)
        .where(AnalysisMessage.run_id == run.id, AnalysisMessage.role == "assistant")
        .order_by(AnalysisMessage.created_at.desc())
    )
    assert message is not None
    assert message.content == "你是想调整上一轮的展示方式，还是开始分析新的指标？"
    assert "agent.clarification_required" not in message.content


def test_switch_topic_does_not_seed_the_previous_metric_intent() -> None:
    db, user, workspace = _database()
    conversation_id, _, _ = _completed_first_turn(db, user, workspace)
    turn, run = _send_follow_up(
        db,
        user,
        workspace,
        conversation_id,
        key="switch-follow-up",
        message="换个话题，数据库有哪些表？",
    )
    gateway = FakeGateway(
        [
            GatewayResponse(
                "new-intent-1",
                "fake",
                json.dumps(
                    {
                        "domain": "manufacturing_quality",
                        "task_type": "catalog_exploration",
                        "goal": "数据库有哪些表？",
                        "metrics": [],
                        "dimensions": [],
                        "filters": {},
                        "time_range": None,
                        "comparison": None,
                        "output": ["table"],
                        "ambiguities": [],
                        "confidence": 1.0,
                    },
                    ensure_ascii=False,
                ),
                None,
                (),
                "stop",
                GatewayUsage(20, 10, 30),
            )
        ]
    )

    run_analysis(db, run_id=run.id, gateway=gateway)
    db.refresh(run)
    db.refresh(turn)

    assert turn.relation is AnalysisTurnRelation.SWITCH_TOPIC
    assert run.context["intent"]["task_type"] == "catalog_exploration"
    assert run.context["intent"]["metrics"] == []
    assert run.context["follow_up_relation"] == "switch_topic"
