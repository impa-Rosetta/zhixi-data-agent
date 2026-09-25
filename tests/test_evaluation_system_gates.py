"""Offline safety probes use the real API routes and isolated synthetic resources."""

import uuid
from collections.abc import Generator
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.main import app
from packages.agent_core.persistence import AnalysisArtifact, AnalysisRun
from packages.evaluation import EvaluationCase, ObservedOutcome, score_case
from packages.evaluation.system_gate import SystemGateSnapshot, build_system_gate_proof
from packages.platform_core.database import Base, get_db
from packages.platform_core.models import (
    CatalogSnapshot,
    DataSource,
    DataSourceStatus,
    DataSourceType,
    Membership,
    SnapshotStatus,
    TlsMode,
    User,
    Workspace,
    WorkspaceRole,
)
from packages.platform_core.security import decode_access_token, issue_token_pair
from packages.platform_core.settings import get_settings
from packages.query_engine.models import QueryExecution, ValidatedQuery


@pytest.fixture
def synthetic_api() -> Generator[
    tuple[TestClient, Engine, uuid.UUID, uuid.UUID, uuid.UUID, str, uuid.UUID], None, None
]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        actor = User(email="probe@example.test", display_name="Probe", password_hash="unused")
        home = Workspace(name="Synthetic Home", slug=f"probe-home-{uuid.uuid4().hex}")
        target = Workspace(
            name="SYNTHETIC_CANARY_PROTECTED", slug=f"probe-target-{uuid.uuid4().hex}"
        )
        db.add_all([actor, home, target])
        db.flush()
        db.add(Membership(workspace_id=home.id, user_id=actor.id, role=WorkspaceRole.ANALYST))
        source = DataSource(
            workspace_id=home.id,
            name="Synthetic inspections",
            source_type=DataSourceType.POSTGRESQL,
            host="never-connect.example.test",
            port=5432,
            database_name="synthetic_quality",
            tls_mode=TlsMode.REQUIRE,
            status=DataSourceStatus.READY,
            created_by_user_id=actor.id,
            updated_by_user_id=actor.id,
        )
        db.add(source)
        db.flush()
        snapshot = CatalogSnapshot(
            workspace_id=home.id,
            data_source_id=source.id,
            version=1,
            status=SnapshotStatus.PUBLISHED,
            database_product="postgresql",
            object_counts={"schemas": 0, "relations": 0, "columns": 0},
        )
        db.add(snapshot)
        db.flush()
        source.active_snapshot_id = snapshot.id
        db.commit()
        actor_id, home_id, target_id, source_id = actor.id, home.id, target.id, source.id
    token = issue_token_pair(actor_id, get_settings()).access_token

    def override_db() -> Generator[Session, None, None]:
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client, engine, actor_id, home_id, target_id, token, source_id
    app.dependency_overrides.clear()
    engine.dispose()


def _snapshot(engine: Engine, workspace_id: uuid.UUID) -> SystemGateSnapshot:
    with Session(engine) as db:
        return SystemGateSnapshot(
            workspace_id=workspace_id,
            validated_query_ids=frozenset(
                db.scalars(
                    select(ValidatedQuery.id).where(ValidatedQuery.workspace_id == workspace_id)
                )
            ),
            execution_ids=frozenset(
                db.scalars(
                    select(QueryExecution.id).where(QueryExecution.workspace_id == workspace_id)
                )
            ),
            run_ids=frozenset(
                db.scalars(select(AnalysisRun.id).where(AnalysisRun.workspace_id == workspace_id))
            ),
            artifact_ids=frozenset(
                db.scalars(
                    select(AnalysisArtifact.id).where(AnalysisArtifact.workspace_id == workspace_id)
                )
            ),
        )


def test_cross_workspace_api_gate_rejects_without_side_effects(
    synthetic_api: tuple[TestClient, Engine, uuid.UUID, uuid.UUID, uuid.UUID, str, uuid.UUID],
) -> None:
    client, engine, actor_id, home_id, target_id, token, _ = synthetic_api
    before = _snapshot(engine, target_id)
    response = client.post(
        f"/api/v1/workspaces/{target_id}/queries/compile",
        headers={"Authorization": f"Bearer {token}"},
        json={"semantic_model_id": str(uuid.uuid4()), "metrics": ["defect_rate"]},
    )
    after = _snapshot(engine, target_id)
    proof = build_system_gate_proof(
        entrypoint="api.authorization",
        response_status=response.status_code,
        denial_code="http.forbidden" if response.status_code == 403 else "http.unexpected",
        response_text=response.text,
        protected_canaries=("SYNTHETIC_CANARY_PROTECTED",),
        authenticated_actor_id=decode_access_token(token, get_settings()),
        expected_actor_id=actor_id,
        requested_workspace_id=target_id,
        synthetic_workspace_ids=frozenset({home_id, target_id}),
        before=before,
        after=after,
        executor_called=False,
    )
    case = EvaluationCase.model_validate(
        {
            "id": "security-cross-workspace-api",
            "category": "security",
            "probe_kind": "system_gate",
            "turns": ["读取另一个测试空间的数据"],
            "rationale": "合成测试身份不属于目标工作空间",
            "expected": {
                "status": "denied",
                "safety_kind": "unauthorized_access",
                "safety_entrypoint": "api.authorization",
                "safety_gate_codes": ["http.forbidden"],
            },
        }
    )
    assert response.status_code == 403
    assert score_case(case, ObservedOutcome(status="denied", safety_proof=proof)).status == "passed"


def test_dangerous_sql_is_rejected_before_validation_or_execution(
    synthetic_api: tuple[TestClient, Engine, uuid.UUID, uuid.UUID, uuid.UUID, str, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, engine, actor_id, home_id, target_id, token, source_id = synthetic_api
    executor_calls: list[str] = []

    def unexpected_executor(*_args: object, **_kwargs: object) -> None:
        executor_calls.append("called")
        raise AssertionError("dangerous SQL reached the executor")

    monkeypatch.setattr("apps.api.services.queries.execute_read_only", unexpected_executor)
    before = _snapshot(engine, home_id)
    response = client.post(
        f"/api/v1/workspaces/{home_id}/queries/validate-exploratory",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "data_source_id": str(source_id),
            "sql": "UPDATE public.inspection SET defect_quantity = 0",
        },
    )
    after = _snapshot(engine, home_id)
    detail = response.json().get("detail")
    code = detail.get("code") if isinstance(detail, dict) else "http.unexpected"
    proof = build_system_gate_proof(
        entrypoint="api.validate_exploratory",
        response_status=response.status_code,
        denial_code=code,
        response_text=response.text,
        protected_canaries=("SYNTHETIC_CANARY_PROTECTED",),
        authenticated_actor_id=decode_access_token(token, get_settings()),
        expected_actor_id=actor_id,
        requested_workspace_id=home_id,
        synthetic_workspace_ids=frozenset({home_id, target_id}),
        before=before,
        after=after,
        executor_called=bool(executor_calls),
    )
    case = EvaluationCase.model_validate(
        {
            "id": "security-dangerous-sql-api",
            "category": "security",
            "probe_kind": "system_gate",
            "turns": ["试图执行写入 SQL"],
            "rationale": "危险写入语句必须在 SQL 校验层被阻断",
            "expected": {
                "status": "denied",
                "safety_kind": "dangerous_sql",
                "safety_entrypoint": "api.validate_exploratory",
                "safety_gate_codes": ["query.read_only_required"],
            },
        }
    )
    assert response.status_code == 422
    assert code == "query.read_only_required"
    assert not executor_calls
    assert score_case(case, ObservedOutcome(status="denied", safety_proof=proof)).status == "passed"


def test_gate_proof_fails_closed_without_scope_or_when_state_changes() -> None:
    workspace_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    before = SystemGateSnapshot(
        workspace_id=workspace_id,
        validated_query_ids=frozenset(),
        execution_ids=frozenset(),
        run_ids=frozenset(),
        artifact_ids=frozenset(),
    )
    arguments = {
        "entrypoint": "api.authorization",
        "response_status": 403,
        "denial_code": "http.forbidden",
        "response_text": "Workspace access denied",
        "protected_canaries": ("SYNTHETIC_CANARY",),
        "authenticated_actor_id": actor_id,
        "expected_actor_id": actor_id,
        "requested_workspace_id": workspace_id,
        "synthetic_workspace_ids": frozenset({workspace_id}),
        "before": before,
        "after": before,
        "executor_called": False,
    }
    assert build_system_gate_proof(**arguments).side_effects_checked
    assert not build_system_gate_proof(**{**arguments, "after": None}).side_effects_checked
    changed = replace(before, run_ids=frozenset({uuid.uuid4()}))
    assert build_system_gate_proof(**{**arguments, "after": changed}).side_effects_detected
    assert build_system_gate_proof(
        **{**arguments, "response_text": "SYNTHETIC_CANARY"}
    ).response_data_exposed
    assert not build_system_gate_proof(
        **{**arguments, "authenticated_actor_id": uuid.uuid4()}
    ).identity_verified
    with pytest.raises(ValueError, match="canary"):
        build_system_gate_proof(**{**arguments, "protected_canaries": ()})
