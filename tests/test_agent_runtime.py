import asyncio
import json
import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.services.analysis_runs import (
    append_message,
    create_run,
    get_run_view,
    stream_events,
)
from apps.worker.analysis_runtime import run_analysis
from packages.agent_core.persistence import AnalysisEvent, AnalysisRun, AnalysisRunStatus
from packages.connectors.metadata import (
    MetadataColumn,
    MetadataDocument,
    MetadataRelation,
    MetadataSchema,
)
from packages.model_gateway import FakeGateway, GatewayResponse, GatewayUsage
from packages.platform_core.catalog_store import replace_snapshot_document
from packages.platform_core.database import Base
from packages.platform_core.models import (
    CatalogSnapshot,
    DataSource,
    DataSourceStatus,
    DataSourceType,
    SnapshotStatus,
    TlsMode,
    User,
    Workspace,
)
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


def _fake_sequence(*contents: dict[str, object]) -> FakeGateway:
    return FakeGateway(
        [
            GatewayResponse(
                f"fake-{index}",
                "fake",
                json.dumps(content, ensure_ascii=False),
                None,
                (),
                "stop",
                GatewayUsage(20, 10, 30),
            )
            for index, content in enumerate(contents, start=1)
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


def _published_catalog(
    db: Session,
    user: User,
    workspace: Workspace,
    *,
    name: str = "制造质量库",
) -> DataSource:
    source = DataSource(
        workspace_id=workspace.id,
        name=name,
        source_type=DataSourceType.POSTGRESQL,
        host="never-return.example",
        port=5432,
        database_name="never_return",
        tls_mode=TlsMode.REQUIRE,
        status=DataSourceStatus.READY,
        created_by_user_id=user.id,
        updated_by_user_id=user.id,
    )
    db.add(source)
    db.flush()
    snapshot = CatalogSnapshot(
        workspace_id=workspace.id,
        data_source_id=source.id,
        version=2,
        status=SnapshotStatus.PUBLISHED,
        database_product="postgresql",
        database_version="16.4",
        object_counts={"schemas": 1, "relations": 1, "columns": 2},
        content_digest="c" * 64,
        sampling_enabled=False,
    )
    db.add(snapshot)
    db.flush()
    replace_snapshot_document(
        db,
        snapshot_id=snapshot.id,
        workspace_id=workspace.id,
        data_source_id=source.id,
        document=MetadataDocument(
            database_product="postgresql",
            database_version="16.4",
            schemas=(MetadataSchema("public", "业务数据"),),
            relations=(
                MetadataRelation(
                    schema="public",
                    name="inspection",
                    relation_type="table",
                    comment="质检记录",
                    columns=(
                        MetadataColumn("defect_quantity", 1, "number", "integer", False),
                        MetadataColumn("inspected_quantity", 2, "number", "integer", False),
                    ),
                    constraints=(),
                    indexes=(),
                ),
            ),
        ),
    )
    source.active_snapshot_id = snapshot.id
    db.commit()
    return source


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
    assert stored.context["clarification"] == {
        "reason_code": "metric_required",
        "question": "你希望分析哪个指标？",
        "missing_fields": ["metrics"],
        "candidates": [],
        "suggested_answers": ["分析不良率", "分析一次通过率", "分析返工率"],
        "resume_node": "understand",
    }
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
    assert stored.context["intent"]["goal"] == "看看那个比例"
    assert stored.context["intent_revision_pending"] is True


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
    assert stored.model_calls == 1
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


def test_runtime_completes_capability_help_without_semantic_or_data_access() -> None:
    db, user, workspace = _database()
    run_id = create_run(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="capability-help",
        payload=CreateAnalysisRunRequest(message="这是个什么 Agent"),
    ).id
    gateway = _fake(
        {
            "domain": "manufacturing_quality",
            "task_type": "unsupported",
            "goal": "错误的模型分类",
            "metrics": [],
            "confidence": 0.99,
        }
    )
    run_analysis(db, run_id=run_id, gateway=gateway)
    stored = db.get(AnalysisRun, run_id)
    assert stored is not None
    assert stored.status is AnalysisRunStatus.COMPLETED
    assert stored.context["route"]["route"] == "capability_help"
    assert stored.model_calls == 0
    assert stored.tool_calls == 1
    view = get_run_view(db, workspace_id=workspace.id, run_id=run_id)
    assert view.plan is not None
    assert view.steps[0].tool_name == "system.capabilities"
    assert view.tool_calls[0].tool_name == "system.capabilities"
    assert view.artifacts[0].artifact_type == "assistant_message"
    assert view.artifacts[0].summary["manifest_version"] == "1.0.0"
    assert "可信指标查询" in str(view.artifacts[0].summary["message"])
    assert view.evidence[0].evidence_type == "capability_manifest"
    assert view.validations[0].validation_type == "capability_scope"
    assert view.validations[0].outcome == "passed"


def test_capability_help_respects_tool_budget_and_fails_inside_run_lifecycle() -> None:
    db, user, workspace = _database()
    run_id = create_run(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="capability-budget",
        payload=CreateAnalysisRunRequest(message="你能做什么", max_tool_calls=1),
    ).id
    stored = db.get(AnalysisRun, run_id)
    assert stored is not None
    stored.tool_calls = 1
    db.commit()
    run_analysis(
        db,
        run_id=run_id,
        gateway=_fake(
            {
                "domain": "manufacturing_quality",
                "task_type": "capability_help",
                "goal": "介绍能力",
                "metrics": [],
                "confidence": 0.99,
            }
        ),
    )
    assert stored.status is AnalysisRunStatus.FAILED
    assert stored.error_code == "agent.tool_budget_exhausted"
    view = get_run_view(db, workspace_id=workspace.id, run_id=run_id)
    assert view.artifacts == []


def test_runtime_searches_only_published_catalogs_in_the_run_workspace() -> None:
    db, user, workspace = _database()
    source = _published_catalog(db, user, workspace)
    other = Workspace(name="Other", slug=f"other-{uuid.uuid4().hex}")
    db.add(other)
    db.flush()
    _published_catalog(db, user, other, name="禁止泄露的数据源")
    run_id = create_run(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="catalog-search",
        payload=CreateAnalysisRunRequest(message="inspection 表有哪些字段"),
    ).id
    run_analysis(
        db,
        run_id=run_id,
        gateway=_fake(
            {
                "domain": "manufacturing_quality",
                "task_type": "catalog_exploration",
                "goal": "inspection 表有哪些字段",
                "metrics": [],
                "confidence": 0.98,
            }
        ),
    )
    stored = db.get(AnalysisRun, run_id)
    assert stored is not None and stored.status is AnalysisRunStatus.COMPLETED
    view = get_run_view(db, workspace_id=workspace.id, run_id=run_id)
    result = view.artifacts[0].summary
    assert view.steps[0].tool_name == "catalog.search"
    assert view.artifacts[0].artifact_type == "catalog_result"
    assert result["sources"][0]["id"] == str(source.id)
    assert result["sources"][0]["relations"][0]["name"] == "inspection"
    assert [item["name"] for item in result["sources"][0]["relations"][0]["columns"]] == [
        "defect_quantity",
        "inspected_quantity",
    ]
    serialized = json.dumps(result, ensure_ascii=False)
    assert "禁止泄露的数据源" not in serialized
    assert "never-return.example" not in serialized
    assert "never_return" not in serialized
    assert view.evidence[0].evidence_type == "catalog_snapshot"
    assert {item.validation_type for item in view.validations} == {
        "authorization_scope",
        "sensitive_output",
    }


def test_catalog_search_fails_actionably_when_no_published_catalog_exists() -> None:
    db, user, workspace = _database()
    run_id = create_run(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="catalog-empty",
        payload=CreateAnalysisRunRequest(message="表格中有什么数据"),
    ).id
    run_analysis(
        db,
        run_id=run_id,
        gateway=_fake(
            {
                "domain": "manufacturing_quality",
                "task_type": "catalog_exploration",
                "goal": "表格中有什么数据",
                "metrics": [],
                "confidence": 0.95,
            }
        ),
    )
    stored = db.get(AnalysisRun, run_id)
    assert stored is not None
    assert stored.status is AnalysisRunStatus.FAILED
    assert stored.error_code == "catalog.not_available"
    assert get_run_view(db, workspace_id=workspace.id, run_id=run_id).artifacts == []


def test_runtime_merges_clarification_patch_and_replays_route_defaults() -> None:
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
        content_digest="d" * 64,
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
        idempotency_key="clarification-patch",
        payload=CreateAnalysisRunRequest(message="分析质量指标"),
    ).id
    gateway = _fake_sequence(
        {
            "domain": "manufacturing_quality",
            "task_type": "metric_query",
            "goal": "分析质量指标",
            "metrics": [],
            "confidence": 0.45,
        },
        {
            "mode": "patch",
            "patch": {"metrics": ["不良率"]},
            "replacement": None,
        },
    )
    run_analysis(db, run_id=run_id, gateway=gateway)
    append_message(
        db,
        workspace_id=workspace.id,
        run_id=run_id,
        actor_user_id=user.id,
        idempotency_key="clarification-patch-answer",
        payload=AppendAnalysisMessageRequest(message="我指的是不良率"),
    )
    result = {
        "validated_query_id": str(uuid.uuid4()),
        "execution_id": str(uuid.uuid4()),
        "columns": ["defect_rate"],
        "rows": [[1.5]],
        "evidence_digest": "e" * 64,
        "trust": "trusted",
    }
    run_analysis(db, run_id=run_id, gateway=gateway, metric_executor=lambda *_: result)
    stored = db.get(AnalysisRun, run_id)
    assert stored is not None and stored.status is AnalysisRunStatus.COMPLETED
    assert stored.context["intent"]["goal"] == "分析质量指标"
    assert stored.context["intent"]["metrics"] == ["不良率"]
    assert stored.context["intent_revision"] == 2
    assert stored.context["defaults_applied"] == {
        "time_range": "all_available",
        "dimensions": "aggregate",
    }
    assert stored.model_calls == 2
    event_types = list(
        db.scalars(
            select(AnalysisEvent.event_type)
            .where(AnalysisEvent.run_id == run_id)
            .order_by(AnalysisEvent.sequence)
        )
    )
    assert "run.intent_revised" in event_types
    assert "run.route_selected" in event_types
    assert "run.defaults_applied" in event_types


def test_event_stream_sends_heartbeat_while_run_is_active(
    monkeypatch,
) -> None:
    db, user, workspace = _database()
    run_id = create_run(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="heartbeat",
        payload=CreateAnalysisRunRequest(message="保持事件连接"),
    ).id
    db.commit()
    ticks = iter([0.0, 2.0])
    monkeypatch.setattr(
        "apps.api.services.analysis_runs.monotonic",
        lambda: next(ticks),
    )
    stream = stream_events(
        db,
        workspace_id=workspace.id,
        run_id=run_id,
        heartbeat_seconds=1.0,
    )

    async def read_stream() -> tuple[str, str]:
        first = await anext(stream)
        second = await anext(stream)
        await stream.aclose()
        return first, second

    first, second = asyncio.run(read_stream())
    assert "event: run.created" in first
    assert second == ": keep-alive\n\n"
