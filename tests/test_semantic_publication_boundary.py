"""Publication identity boundaries on the real Agent loader and clarification path."""

import json
import os
import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.services.analysis_runs import create_run, get_run_view
from apps.worker.analysis_runtime import _published_semantics, run_analysis
from packages.agent_core.contracts import Intent
from packages.agent_core.persistence import AnalysisRun, AnalysisRunStatus
from packages.agent_core.planner import bind_intent
from packages.evaluation.semantic_ambiguity_fixture import SemanticAmbiguity, seed_semantics
from packages.model_gateway import FakeGateway, GatewayResponse, GatewayUsage
from packages.platform_core.database import Base
from packages.platform_core.models import User, Workspace
from packages.semantic_model.models import (
    SemanticModel,
    SemanticModelStatus,
    SemanticModelVersion,
    SemanticVersionStatus,
)
from packages.shared_contracts.agents import CreateAnalysisRunRequest


@pytest.fixture
def db() -> Generator[Session, None, None]:
    url = os.getenv("SEMANTIC_BOUNDARY_POSTGRES_URL")
    schema = f"semantic_boundary_{uuid.uuid4().hex}" if url else None
    engine = (
        create_engine(url)
        if url
        else create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    )
    if schema:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        bind = engine.execution_options(schema_translate_map={None: schema})
    else:
        bind = engine
    try:
        Base.metadata.create_all(bind)
        with Session(bind) as session:
            yield session
    finally:
        if schema:
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def _seed(db: Session) -> tuple[User, Workspace, SemanticModel, SemanticModelVersion, AnalysisRun]:
    user = User(email="boundary@example.invalid", display_name="Synthetic", password_hash="hash")
    workspace = Workspace(name="Synthetic boundary", slug="synthetic-boundary")
    db.add_all([user, workspace])
    db.flush()
    model = seed_semantics(db, user, workspace, SemanticAmbiguity("分析不良率", "不良率", 1))[0]
    version = db.get(SemanticModelVersion, model.active_version_id)
    assert version is not None
    created = create_run(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="boundary",
        payload=CreateAnalysisRunRequest(message="分析不良率"),
    )
    run = db.get(AnalysisRun, created.id)
    assert run is not None
    db.commit()
    return user, workspace, model, version, run


@pytest.mark.parametrize(
    "state",
    [
        "archived",
        "draft_model",
        "draft_version",
        "foreign_version",
        "foreign_version_workspace",
        "other_model_version",
        "no_active_version",
    ],
)
def test_invalid_publication_identity_is_not_loaded_or_executed(db: Session, state: str) -> None:
    user, workspace, model, version, run = _seed(db)
    assert len(_published_semantics(db, run)) == 1
    if state == "archived":
        model.status = SemanticModelStatus.ARCHIVED
    elif state == "draft_model":
        model.status = SemanticModelStatus.DRAFT
    elif state == "draft_version":
        version.status = SemanticVersionStatus.DRAFT
    elif state == "no_active_version":
        model.active_version_id = None
    else:
        foreign = Workspace(name="SYNTHETIC_PRIVATE_SEMANTIC_CANARY", slug="foreign-boundary")
        db.add(foreign)
        db.flush()
        if state == "foreign_version_workspace":
            version.workspace_id = foreign.id
        else:
            target = foreign if state == "foreign_version" else workspace
            other = SemanticModel(
                workspace_id=target.id,
                name="SYNTHETIC_PRIVATE_SEMANTIC_CANARY",
                status=SemanticModelStatus.DRAFT,
                created_by_user_id=user.id,
                updated_by_user_id=user.id,
            )
            db.add(other)
            db.flush()
            other_version = SemanticModelVersion(
                workspace_id=target.id,
                semantic_model_id=other.id,
                revision=1,
                status=SemanticVersionStatus.PUBLISHED,
                document=dict(version.document),
                content_digest="b" * 64,
                created_by_user_id=user.id,
            )
            db.add(other_version)
            db.flush()
            model.active_version_id = other_version.id
    db.commit()
    assert _published_semantics(db, run) == ()
    gateway = FakeGateway(
        [
            GatewayResponse(
                "boundary",
                "fake",
                json.dumps(
                    {
                        "domain": "manufacturing_quality",
                        "task_type": "metric_query",
                        "goal": "分析不良率",
                        "metrics": ["不良率"],
                        "confidence": 0.98,
                    }
                ),
                None,
                (),
                "stop",
                GatewayUsage(20, 10, 30),
            )
        ]
    )
    executor_calls: list[int] = []

    def forbidden_executor(*_: object) -> dict[str, object]:
        executor_calls.append(1)
        raise AssertionError("Invalid publication reached the executor")

    run_analysis(db, run_id=run.id, gateway=gateway, metric_executor=forbidden_executor)
    db.refresh(run)
    view = get_run_view(db, workspace_id=workspace.id, run_id=run.id)
    assert run.status is AnalysisRunStatus.WAITING_FOR_CLARIFICATION
    assert executor_calls == []
    assert view.tool_calls == [] and view.evidence == []
    assert not any(item.artifact_type == "query_result" for item in view.artifacts)
    replies = [message.content for message in view.messages if message.role == "assistant"]
    assert replies and all(reply.strip() for reply in replies)
    assert "SYNTHETIC_PRIVATE_SEMANTIC_CANARY" not in view.model_dump_json()


def test_republished_own_version_is_loaded_and_bound_again(db: Session) -> None:
    _, _, model, version, run = _seed(db)
    model.status = SemanticModelStatus.ARCHIVED
    db.commit()
    assert _published_semantics(db, run) == ()
    model.status = SemanticModelStatus.PUBLISHED
    db.commit()
    semantics = _published_semantics(db, run)
    assert len(semantics) == 1
    assert semantics[0].model_id == str(model.id)
    assert semantics[0].version_id == str(version.id)
    binding = bind_intent(
        Intent(task_type="metric_query", goal="分析不良率", metrics=("不良率",), confidence=0.98),
        semantics,
    )
    assert binding.semantic_model_id == str(model.id)
    assert binding.semantic_version_id == str(version.id)
    assert binding.metric_keys == ("defect_rate",)
    assert (
        db.scalar(
            select(SemanticModelVersion.status).where(
                SemanticModelVersion.id == version.id,
            )
        )
        is SemanticVersionStatus.PUBLISHED
    )
