import json
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.services.analysis_runs import append_message, create_run, get_run_view
from apps.worker.analysis_runtime import run_analysis
from packages.agent_core.persistence import AnalysisRun, AnalysisRunStatus
from packages.model_gateway import FakeGateway, GatewayResponse, GatewayUsage
from packages.platform_core.database import Base
from packages.platform_core.models import User, Workspace
from packages.semantic_model.manufacturing import manufacturing_quality_template
from packages.semantic_model.models import (
    SemanticModel,
    SemanticModelStatus,
    SemanticModelVersion,
    SemanticVersionStatus,
)
from packages.shared_contracts.agents import (
    AppendAnalysisMessageRequest,
    CreateAnalysisRunRequest,
)


def _fake(content: dict[str, object]) -> FakeGateway:
    return FakeGateway(
        [
            GatewayResponse(
                "fake-1",
                "fake",
                json.dumps(content, ensure_ascii=False),
                None,
                (),
                "stop",
                GatewayUsage(20, 10, 30),
            )
        ]
    )


def _database() -> tuple[Session, User, Workspace]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = User(
        email="owner@example.com",
        display_name="Owner",
        password_hash="hash",
    )
    workspace = Workspace(name="Factory", slug=f"factory-{uuid.uuid4().hex}")
    db.add_all([user, workspace])
    db.flush()
    return db, user, workspace


def test_runtime_pauses_low_confidence_and_is_idempotent() -> None:
    db, user, workspace = _database()
    run_id = create_run(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="low-confidence",
        payload=CreateAnalysisRunRequest(message="看看那个比例"),
    ).id
    gateway = _fake(
        {
            "domain": "manufacturing_quality",
            "task_type": "metric_query",
            "goal": "看看那个比例",
            "metrics": [],
            "confidence": 0.4,
        }
    )
    run_analysis(db, run_id=run_id, gateway=gateway)
    run_analysis(db, run_id=run_id, gateway=gateway)
    stored = db.get(AnalysisRun, run_id)
    assert stored is not None
    assert stored.status is AnalysisRunStatus.WAITING_FOR_CLARIFICATION
    assert len(gateway.calls) == 1
    append_message(
        db,
        workspace_id=workspace.id,
        run_id=run_id,
        actor_user_id=user.id,
        idempotency_key="clarification-1",
        payload=AppendAnalysisMessageRequest(message="我指的是不良率"),
    )
    assert stored.status is AnalysisRunStatus.QUEUED
    assert "intent" not in stored.context


def test_runtime_persists_plan_result_and_evidence() -> None:
    db, user, workspace = _database()
    document = manufacturing_quality_template()
    model = SemanticModel(
        workspace_id=workspace.id,
        name="Quality",
        status=SemanticModelStatus.PUBLISHED,
        created_by_user_id=user.id,
        updated_by_user_id=user.id,
    )
    db.add(model)
    db.flush()
    version = SemanticModelVersion(
        workspace_id=workspace.id,
        semantic_model_id=model.id,
        revision=1,
        status=SemanticVersionStatus.PUBLISHED,
        document=document.model_dump(mode="json"),
        counts={},
        content_digest="a" * 64,
        created_by_user_id=user.id,
        published_by_user_id=user.id,
    )
    db.add(version)
    db.flush()
    model.active_version_id = version.id
    run_id = create_run(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="trusted-query",
        payload=CreateAnalysisRunRequest(message="分析不良率"),
    ).id
    gateway = _fake(
        {
            "domain": "manufacturing_quality",
            "task_type": "metric_query",
            "goal": "分析不良率",
            "metrics": ["不良率"],
            "confidence": 0.98,
        }
    )
    result = {
        "validated_query_id": str(uuid.uuid4()),
        "execution_id": str(uuid.uuid4()),
        "columns": ["defect_rate"],
        "rows": [[2.5]],
        "evidence_digest": "b" * 64,
        "trust": "trusted",
    }
    run_analysis(db, run_id=run_id, gateway=gateway, metric_executor=lambda *_: result)
    stored = db.get(AnalysisRun, run_id)
    assert stored is not None
    assert stored.status is AnalysisRunStatus.COMPLETED
    assert stored.context["result"]["rows"] == [[2.5]]
    assert stored.total_tokens == 30
    view = get_run_view(db, workspace_id=workspace.id, run_id=run_id)
    assert view.plan is not None
    assert view.plan.goal == "分析不良率"
    assert len(view.steps) == 1
    assert view.steps[0].tool_name == "query.metric"
    assert len(view.tool_calls) == 1
    assert view.tool_calls[0].result_summary["rows"] == [[2.5]]
    assert len(view.artifacts) == 1
    assert view.artifacts[0].summary["rows"] == [[2.5]]
    assert len(view.evidence) == 1
    assert view.evidence[0].evidence_digest == "b" * 64
    assert len(view.validations) == 1
    assert view.validations[0].outcome == "passed"
    assert view.last_event_sequence >= 1
