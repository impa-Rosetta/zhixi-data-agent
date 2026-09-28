"""Persisted query execution guards and evidence, with synthetic data only."""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.services import queries
from packages.connectors.base import ConnectorCredentials, ConnectorError
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
from packages.query_engine.models import (
    QueryExecution,
    QueryExecutionStatus,
    QueryTrust,
    ValidatedQuery,
)
from packages.query_engine.runtime import QueryResult


@pytest.fixture
def query_db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        actor = User(
            email="query-service@example.test", display_name="Query Probe", password_hash="unused"
        )
        home = Workspace(name="Query Home", slug=f"query-home-{uuid.uuid4().hex}")
        other = Workspace(name="Other", slug=f"query-other-{uuid.uuid4().hex}")
        db.add_all([actor, home, other])
        db.flush()
        source = DataSource(
            workspace_id=home.id,
            name="Synthetic source",
            source_type=DataSourceType.POSTGRESQL,
            host="never-connect.example.test",
            port=5432,
            database_name="synthetic",
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
        item = ValidatedQuery(
            workspace_id=home.id,
            data_source_id=source.id,
            snapshot_id=snapshot.id,
            semantic_model_id=None,
            semantic_version_id=None,
            dialect="postgres",
            trust=QueryTrust.EXPLORATORY,
            protocol={},
            sql_text="SELECT 1 AS value",
            parameters=[],
            dependencies=["public.synthetic"],
            safety_report={"outcome": "approved"},
            digest="a" * 64,
            row_limit=10,
            created_by_user_id=actor.id,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            created_at=datetime.now(UTC),
        )
        db.add(item)
        db.commit()
        yield db, item, source, snapshot, actor.id, home.id, other.id
    engine.dispose()


def test_other_workspace_cannot_execute_or_persist(query_db, monkeypatch) -> None:
    db, item, _, _, actor_id, _, other_id = query_db
    monkeypatch.setattr(
        queries, "load_runtime_credentials", lambda *_args: pytest.fail("connected")
    )
    with pytest.raises(queries.QueryServiceError, match="Validated query not found") as caught:
        queries.execute_query(
            db, workspace_id=other_id, actor_user_id=actor_id, validated_query_id=item.id
        )
    assert caught.value.code == "query.not_found"
    assert db.scalar(select(QueryExecution.id)) is None


def test_expired_validation_does_not_connect(query_db, monkeypatch) -> None:
    db, item, _, _, actor_id, home_id, _ = query_db
    item.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    monkeypatch.setattr(
        queries, "load_runtime_credentials", lambda *_args: pytest.fail("connected")
    )
    with pytest.raises(queries.QueryServiceError, match="expired") as caught:
        queries.execute_query(
            db, workspace_id=home_id, actor_user_id=actor_id, validated_query_id=item.id
        )
    assert caught.value.code == "query.validation_expired"
    assert db.scalar(select(QueryExecution.id)) is None


def test_snapshot_change_requires_new_validation(query_db, monkeypatch) -> None:
    db, item, source, _, actor_id, home_id, _ = query_db
    replacement = CatalogSnapshot(
        workspace_id=home_id,
        data_source_id=source.id,
        version=2,
        status=SnapshotStatus.PUBLISHED,
        database_product="postgresql",
        object_counts={"schemas": 0, "relations": 0, "columns": 0},
    )
    db.add(replacement)
    db.flush()
    source.active_snapshot_id = replacement.id
    monkeypatch.setattr(
        queries, "load_runtime_credentials", lambda *_args: pytest.fail("connected")
    )
    with pytest.raises(queries.QueryServiceError, match="Catalog changed") as caught:
        queries.execute_query(
            db, workspace_id=home_id, actor_user_id=actor_id, validated_query_id=item.id
        )
    assert caught.value.code == "query.snapshot_changed"
    assert db.scalar(select(QueryExecution.id)) is None


def test_success_persists_masked_rows_and_verifiable_evidence(query_db, monkeypatch) -> None:
    db, item, _, snapshot, actor_id, home_id, _ = query_db
    calls = []
    monkeypatch.setattr(
        queries,
        "load_runtime_credentials",
        lambda *_args: (ConnectorCredentials("reader", "synthetic-only"), object()),
    )
    monkeypatch.setattr(queries, "_sensitive_output_names", lambda *_args: {"secret"})

    def execute(*args, **kwargs):
        calls.append((args, kwargs))
        return QueryResult(("secret", "value"), (("private", 3), (None, 4)), False)

    monkeypatch.setattr(queries, "execute_read_only", execute)
    response = queries.execute_query(
        db, workspace_id=home_id, actor_user_id=actor_id, validated_query_id=item.id
    )
    persisted = db.get(QueryExecution, response.id)
    assert persisted is not None
    assert persisted.status is QueryExecutionStatus.SUCCEEDED
    assert persisted.rows == [["***MASKED***", 3], [None, 4]]
    assert response.rows == persisted.rows
    assert persisted.evidence["query_digest"] == item.digest
    assert persisted.evidence["snapshot_id"] == str(snapshot.id)
    assert persisted.evidence_digest and persisted.result_digest
    canonical_result = json.dumps(
        {"columns": ["secret", "value"], "rows": persisted.rows},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert persisted.result_digest == hashlib.sha256(canonical_result.encode()).hexdigest()
    canonical_evidence = json.dumps(
        persisted.evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    assert persisted.evidence_digest == hashlib.sha256(canonical_evidence.encode()).hexdigest()
    assert calls[0][1]["row_limit"] == 10
    assert calls[0][0][4] == "SELECT 1 AS value"


def test_connector_failure_persists_safe_failure_without_result(query_db, monkeypatch) -> None:
    db, item, _, _, actor_id, home_id, _ = query_db
    monkeypatch.setattr(
        queries,
        "load_runtime_credentials",
        lambda *_args: (ConnectorCredentials("reader", "synthetic-only"), object()),
    )

    def fail(*_args, **_kwargs):
        raise ConnectorError("query.timeout", retryable=True)

    monkeypatch.setattr(queries, "execute_read_only", fail)
    response = queries.execute_query(
        db, workspace_id=home_id, actor_user_id=actor_id, validated_query_id=item.id
    )
    persisted = db.get(QueryExecution, response.id)
    assert persisted is not None
    assert persisted.status is QueryExecutionStatus.FAILED
    assert persisted.error_code == "query.timeout"
    assert persisted.rows == [] and persisted.evidence_digest is None
    assert persisted.evidence["query_digest"] == item.digest
