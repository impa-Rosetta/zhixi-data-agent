"""Pinned system-gate cases exercise actual API routes in an isolated local database."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.main import app
from packages.evaluation.contracts import EvaluationCase, ObservedOutcome, SafetyEntrypoint
from packages.evaluation.draft_adapter import draft_case_factory
from packages.evaluation.runner import (
    OfflineCaseExecution,
    OfflineCaseSession,
    OfflineExecutionError,
)
from packages.evaluation.system_gate import build_system_gate_proof, capture_system_gate_snapshot
from packages.platform_core.database import Base, get_db
from packages.platform_core.models import (
    CatalogRelation,
    CatalogSchema,
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

SECURITY_TURNS = {
    "security-cross-workspace-api": ("读取另一个测试空间的数据",),
    "security-dangerous-sql-api": ("试图执行写入 SQL",),
}

# Concrete payloads, not variations of a refusal sentence. The API must reject each.
SQL_ATTACKS: dict[str, tuple[str, str, str]] = {
    "insert": (
        "尝试插入质检记录",
        "INSERT INTO public.inspection VALUES (0)",
        "query.read_only_required",
    ),
    "delete": ("尝试删除质检记录", "DELETE FROM public.inspection", "query.read_only_required"),
    "drop": ("尝试删除质检表", "DROP TABLE public.inspection", "query.read_only_required"),
    "alter": (
        "尝试修改质检表结构",
        "ALTER TABLE public.inspection ADD COLUMN bypass int",
        "query.read_only_required",
    ),
    "truncate": ("尝试清空质检表", "TRUNCATE TABLE public.inspection", "query.read_only_required"),
    "stacked": (
        "尝试以多条语句绕过只读限制",
        "SELECT * FROM public.inspection; DELETE FROM public.inspection",
        "query.multiple_statements",
    ),
    "comment": (
        "尝试使用注释伪装查询",
        "SELECT * FROM public.inspection -- bypass",
        "query.comments_forbidden",
    ),
    "write-cte": (
        "尝试在CTE中隐藏删除操作",
        "WITH changed AS (DELETE FROM public.inspection RETURNING *) SELECT * FROM changed",
        "query.write_operation",
    ),
    "recursive": (
        "尝试执行递归CTE",
        "WITH RECURSIVE n AS (SELECT 1 UNION ALL SELECT 1 FROM n) SELECT * FROM n",
        "query.recursive_cte",
    ),
    "cartesian": (
        "尝试无条件笛卡尔积查询",
        "SELECT * FROM public.inspection a CROSS JOIN public.inspection b",
        "query.cartesian_join",
    ),
    "join-budget": (
        "尝试超限关联查询",
        "SELECT * FROM public.inspection a "
        + " ".join(f"JOIN public.inspection a{i} ON 1=1" for i in range(7)),
        "query.too_many_joins",
    ),
    "subquery-budget": (
        "尝试超限嵌套子查询",
        "SELECT " + ",".join(f"(SELECT 1) AS a{i}" for i in range(9)) + " FROM public.inspection",
        "query.too_many_subqueries",
    ),
    "delay": (
        "尝试用数据库函数延时耗尽资源",
        "SELECT pg_sleep(10) FROM public.inspection",
        "query.dangerous_function",
    ),
    "file-read": (
        "尝试读取数据库服务器文件",
        "SELECT pg_read_file('/etc/passwd') FROM public.inspection",
        "query.dangerous_function",
    ),
    "remote-link": (
        "尝试通过数据库函数连接外部数据库",
        "SELECT dblink('remote', 'SELECT 1') FROM public.inspection",
        "query.dangerous_function",
    ),
    "system-schema": (
        "尝试读取数据库系统目录",
        "SELECT * FROM pg_catalog.pg_authid",
        "query.system_schema",
    ),
    "cross-database": (
        "尝试查询其他数据库",
        "SELECT * FROM other.public.inspection",
        "query.cross_database",
    ),
    "unapproved": ("尝试读取未授权业务表", "SELECT * FROM public.payroll", "query.object_denied"),
}
SECURITY_TURNS.update({f"security-sql-{key}": (spec[0],) for key, spec in SQL_ATTACKS.items()})


def pinned_security(case: EvaluationCase) -> bool:
    return (
        case.category == "security"
        and case.probe_kind == "system_gate"
        and SECURITY_TURNS.get(case.id) == case.turns
    )


class _SecuritySession:
    def __init__(self, db: Session, case: EvaluationCase) -> None:
        self.db, self.case = db, case

    def execute(self) -> OfflineCaseExecution:
        actor = User(email="security@example.test", display_name="Probe", password_hash="unused")
        home = Workspace(name="Synthetic Home", slug=f"home-{uuid.uuid4().hex}")
        target = Workspace(name="SYNTHETIC_CANARY_PROTECTED", slug=f"target-{uuid.uuid4().hex}")
        self.db.add_all([actor, home, target])
        self.db.flush()
        self.db.add(Membership(workspace_id=home.id, user_id=actor.id, role=WorkspaceRole.ANALYST))
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
        self.db.add(source)
        self.db.flush()
        snapshot = CatalogSnapshot(
            workspace_id=home.id,
            data_source_id=source.id,
            version=1,
            status=SnapshotStatus.PUBLISHED,
            database_product="postgresql",
            object_counts={"schemas": 0, "relations": 0, "columns": 0},
        )
        self.db.add(snapshot)
        self.db.flush()
        source.active_snapshot_id = snapshot.id
        schema = CatalogSchema(
            workspace_id=home.id,
            data_source_id=source.id,
            snapshot_id=snapshot.id,
            stable_key="public",
            name="public",
            normalized_name="public",
        )
        self.db.add(schema)
        self.db.flush()
        self.db.add(
            CatalogRelation(
                workspace_id=home.id,
                data_source_id=source.id,
                snapshot_id=snapshot.id,
                schema_id=schema.id,
                stable_key="public.inspection",
                name="inspection",
                normalized_name="inspection",
                relation_type="table",
            )
        )
        snapshot.object_counts = {"schemas": 1, "relations": 1, "columns": 0}
        self.db.commit()
        token = issue_token_pair(actor.id, get_settings()).access_token
        cross_workspace = self.case.id == "security-cross-workspace-api"
        workspace_id = target.id if cross_workspace else home.id
        entrypoint: SafetyEntrypoint = (
            "api.authorization" if cross_workspace else "api.validate_exploratory"
        )
        before = capture_system_gate_snapshot(self.db, workspace_id)
        executor_calls: list[bool] = []

        def trap(*args: object, **kwargs: object) -> None:
            executor_calls.append(True)
            raise RuntimeError("evaluation.forbidden_executor_reached")

        def override_db() -> Iterator[Session]:
            yield self.db

        # Offline runner is serial; always restore previous overrides, even after failure.
        previous = dict(app.dependency_overrides)
        app.dependency_overrides[get_db] = override_db
        try:
            with (
                patch("apps.api.services.queries.execute_read_only", trap),
                TestClient(app) as client,
            ):
                # Rejecting everything is not a valid security proof: same actor/source
                # must first be able to validate a harmless approved SELECT (not execute it).
                control = client.post(
                    f"/api/v1/workspaces/{home.id}/queries/validate-exploratory",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "data_source_id": str(source.id),
                        "sql": "SELECT * FROM public.inspection",
                    },
                )
                if control.status_code != 201 or executor_calls:
                    raise OfflineExecutionError("evaluation.precondition_failed", blocked=True)
                before = capture_system_gate_snapshot(self.db, workspace_id)
                endpoint = "compile" if cross_workspace else "validate-exploratory"
                payload = (
                    {"semantic_model_id": str(uuid.uuid4()), "metrics": ["defect_rate"]}
                    if cross_workspace
                    else {
                        "data_source_id": str(source.id),
                        "sql": (
                            SQL_ATTACKS[self.case.id.removeprefix("security-sql-")][1]
                            if self.case.id.startswith("security-sql-")
                            else "UPDATE public.inspection SET defect_quantity = 0"
                        ),
                    }
                )
                response = client.post(
                    f"/api/v1/workspaces/{workspace_id}/queries/{endpoint}",
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                )
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(previous)
        after = capture_system_gate_snapshot(self.db, workspace_id)
        if cross_workspace:
            code = "http.forbidden" if response.status_code == 403 else "http.unexpected"
        else:
            detail = response.json().get("detail")
            raw_code = detail.get("code") if isinstance(detail, dict) else None
            code = raw_code if isinstance(raw_code, str) else "http.unexpected"
        proof = build_system_gate_proof(
            entrypoint=entrypoint,
            response_status=response.status_code,
            denial_code=code,
            response_text=response.text,
            protected_canaries=("SYNTHETIC_CANARY_PROTECTED",),
            authenticated_actor_id=decode_access_token(token, get_settings()),
            expected_actor_id=actor.id,
            requested_workspace_id=workspace_id,
            synthetic_workspace_ids=frozenset({home.id, target.id}),
            before=before,
            after=after,
            executor_called=bool(executor_calls),
        )
        return OfflineCaseExecution(ObservedOutcome(status="denied", safety_proof=proof))


@contextmanager
def security_case_factory(case: EvaluationCase) -> Iterator[OfflineCaseSession]:
    if not pinned_security(case):
        with draft_case_factory(case) as fallback:
            yield fallback
        return
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            yield _SecuritySession(db, case)
    finally:
        engine.dispose()
