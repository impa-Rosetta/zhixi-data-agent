"""Real ORM source gate tests. No source DB access or paid model calls."""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from test_analysis_conversation_service import _database

from apps.api.services.advanced_analysis_sources import load_advanced_analysis_input
from apps.api.services.analysis_runs import create_run
from packages.agent_core.persistence import (
    AnalysisArtifact,
    AnalysisEvidence,
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisValidation,
)
from packages.analysis_engine.advanced import AdvancedAnalysisError
from packages.analysis_engine.tools import bind_advanced_analysis_tools
from packages.platform_core.models import (
    CatalogSnapshot,
    DataSource,
    DataSourceStatus,
    DataSourceType,
    Membership,
    SnapshotStatus,
    TlsMode,
    User,
    WorkspaceRole,
)
from packages.query_engine.models import (
    QueryExecution,
    QueryExecutionStatus,
    QueryTrust,
    ValidatedQuery,
)
from packages.semantic_model.models import (
    SemanticModel,
    SemanticModelStatus,
    SemanticModelVersion,
    SemanticVersionStatus,
)
from packages.shared_contracts.agents import CreateAnalysisRunRequest
from packages.toolkit import build_default_registry


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@pytest.fixture
def source_context():
    db, user, workspace = _database()
    member = Membership(workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.ANALYST)
    source = DataSource(
        workspace_id=workspace.id,
        name="Synthetic",
        source_type=DataSourceType.POSTGRESQL,
        host="example.invalid",
        port=5432,
        database_name="synthetic",
        tls_mode=TlsMode.REQUIRE,
        status=DataSourceStatus.READY,
        created_by_user_id=user.id,
        updated_by_user_id=user.id,
    )
    model = SemanticModel(
        workspace_id=workspace.id,
        name="Synthetic",
        status=SemanticModelStatus.PUBLISHED,
        created_by_user_id=user.id,
        updated_by_user_id=user.id,
    )
    db.add_all([member, source, model])
    db.flush()
    snapshot = CatalogSnapshot(
        workspace_id=workspace.id,
        data_source_id=source.id,
        version=1,
        status=SnapshotStatus.PUBLISHED,
        database_product="postgresql",
    )
    version = SemanticModelVersion(
        workspace_id=workspace.id,
        semantic_model_id=model.id,
        revision=1,
        status=SemanticVersionStatus.PUBLISHED,
        document={},
        content_digest="1" * 64,
        created_by_user_id=user.id,
    )
    db.add_all([snapshot, version])
    db.flush()
    source.active_snapshot_id, model.active_version_id = snapshot.id, version.id
    query = ValidatedQuery(
        workspace_id=workspace.id,
        data_source_id=source.id,
        snapshot_id=snapshot.id,
        semantic_model_id=model.id,
        semantic_version_id=version.id,
        dialect="postgres",
        trust=QueryTrust.TRUSTED,
        sql_text="SELECT x, y FROM synthetic",
        digest="2" * 64,
        row_limit=20,
        created_by_user_id=user.id,
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db.add(query)
    db.flush()
    columns, rows = ["x", "y"], [[i, 2 * i] for i in range(10)]
    query_evidence = {
        "validated_query_id": str(query.id),
        "query_digest": query.digest,
        "result_digest": digest({"columns": columns, "rows": rows}),
        "snapshot_id": str(snapshot.id),
        "semantic_version_id": str(version.id),
        "dependencies": [],
        "trust": "trusted",
        "executed_at": datetime.now(UTC).isoformat(),
    }
    execution = QueryExecution(
        workspace_id=workspace.id,
        validated_query_id=query.id,
        status=QueryExecutionStatus.SUCCEEDED,
        columns=columns,
        rows=rows,
        row_count=10,
        truncated=False,
        result_digest=query_evidence["result_digest"],
        evidence=query_evidence,
        evidence_digest=digest(query_evidence),
        requested_by_user_id=user.id,
        finished_at=datetime.now(UTC),
    )
    db.add(execution)
    run_response = create_run(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="advanced-source",
        payload=CreateAnalysisRunRequest(message="分析结果"),
    )
    db.flush()
    run = db.get(AnalysisRun, run_response.id)
    run.status = AnalysisRunStatus.COMPLETED
    summary = {
        "validated_query_id": str(query.id),
        "execution_id": str(execution.id),
        "columns": columns,
        "rows": rows,
        "row_count": 10,
        "truncated": False,
        "evidence_digest": execution.evidence_digest,
        "trust": "trusted",
    }
    artifact = AnalysisArtifact(
        workspace_id=workspace.id,
        run_id=run.id,
        artifact_type="query_result",
        summary=summary,
        content_digest=digest(summary),
    )
    db.add(artifact)
    db.flush()
    evidence = AnalysisEvidence(
        workspace_id=workspace.id,
        run_id=run.id,
        artifact_id=artifact.id,
        evidence_type="query_execution",
        evidence_digest=execution.evidence_digest,
        reference={
            "validated_query_id": str(query.id),
            "execution_id": str(execution.id),
            "semantic_version_id": str(version.id),
            "snapshot_ids": [str(snapshot.id)],
            "trust": "trusted",
        },
    )
    validation = AnalysisValidation(
        workspace_id=workspace.id,
        run_id=run.id,
        validation_type="evidence",
        outcome="passed",
    )
    db.add_all([evidence, validation])
    db.commit()
    try:
        yield (
            db,
            user,
            workspace,
            dict(
                member=member,
                source=source,
                snapshot=snapshot,
                model=model,
                version=version,
                query=query,
                execution=execution,
                run=run,
                artifact=artifact,
                evidence=evidence,
                validation=validation,
            ),
        )
    finally:
        engine = db.get_bind()
        db.close()
        engine.dispose()


def load(context):
    db, user, workspace, records = context
    return load_advanced_analysis_input(
        db, workspace_id=workspace.id, actor_user_id=user.id, artifact_id=records["artifact"].id
    )


def test_real_persistence_loader_and_tool_binding_work_without_reexecuting_sql(
    source_context,
) -> None:
    loaded = load(source_context)
    assert loaded.evidence_id == source_context[3]["evidence"].id
    # The old validation expired; reading this completed result is not a new SQL execution.
    registry = build_default_registry()
    bind_advanced_analysis_tools(registry, lambda _: load(source_context))
    assert registry.invoke(
        "analysis.correlate",
        {"artifact_id": str(loaded.artifact_id), "x_field": "x", "y_field": "y"},
    )["coefficient"] == pytest.approx(1)


@pytest.mark.parametrize("role", list(WorkspaceRole))
def test_current_role_is_rechecked(source_context, role: WorkspaceRole) -> None:
    db, _, _, records = source_context
    records["member"].role = role
    db.commit()
    if role is WorkspaceRole.AUDITOR:
        with pytest.raises(AdvancedAnalysisError, match="policy.denied"):
            load(source_context)
    else:
        assert load(source_context).artifact_id == records["artifact"].id


def test_revoked_membership_rejects_existing_result(source_context) -> None:
    db, _, _, records = source_context
    db.delete(records["member"])
    db.commit()
    with pytest.raises(AdvancedAnalysisError, match="policy.denied"):
        load(source_context)


@pytest.mark.parametrize(
    "record,field,value",
    [
        ("artifact", "workspace_id", uuid.uuid4()),
        ("run", "workspace_id", uuid.uuid4()),
        ("execution", "workspace_id", uuid.uuid4()),
        ("query", "workspace_id", uuid.uuid4()),
        ("source", "workspace_id", uuid.uuid4()),
        ("snapshot", "workspace_id", uuid.uuid4()),
        ("version", "workspace_id", uuid.uuid4()),
        ("evidence", "workspace_id", uuid.uuid4()),
        ("source", "status", DataSourceStatus.DISABLED),
        ("source", "active_snapshot_id", uuid.uuid4()),
        ("snapshot", "data_source_id", uuid.uuid4()),
        ("model", "status", SemanticModelStatus.ARCHIVED),
        ("model", "active_version_id", uuid.uuid4()),
        ("version", "semantic_model_id", uuid.uuid4()),
        ("version", "status", SemanticVersionStatus.DRAFT),
        ("run", "status", AnalysisRunStatus.RUNNING),
        ("query", "trust", QueryTrust.EXPLORATORY),
        ("execution", "status", QueryExecutionStatus.FAILED),
        ("execution", "result_digest", "0" * 64),
        ("execution", "evidence_digest", "0" * 64),
        ("validation", "outcome", "failed"),
        ("evidence", "reference", {}),
        ("artifact", "summary", {}),
    ],
)
def test_invalid_chain_rejected_without_creating_new_records(
    source_context, record, field, value
) -> None:
    db, _, _, records = source_context
    setattr(records[record], field, value)
    db.commit()
    before = db.scalars(select(AnalysisArtifact.id)).all()
    with pytest.raises(AdvancedAnalysisError):
        load(source_context)
    assert db.scalars(select(AnalysisArtifact.id)).all() == before


def test_matching_rehashed_artifact_cannot_override_persisted_query_result(source_context) -> None:
    db, _, _, records = source_context
    artifact = records["artifact"]
    artifact.summary = {**artifact.summary, "rows": [[i, 100] for i in range(10)]}
    artifact.content_digest = digest(artifact.summary)
    db.commit()
    with pytest.raises(AdvancedAnalysisError, match="analysis.digest_mismatch"):
        load(source_context)


def test_truncated_execution_is_rejected_even_when_artifact_matches(source_context) -> None:
    db, _, _, records = source_context
    records["execution"].truncated = True
    artifact = records["artifact"]
    artifact.summary = {**artifact.summary, "truncated": True}
    artifact.content_digest = digest(artifact.summary)
    db.commit()
    with pytest.raises(AdvancedAnalysisError, match="analysis.incomplete_data"):
        load(source_context)


@pytest.mark.parametrize("change", ["role", "inactive", "disabled_source"])
def test_external_changes_are_not_hidden_by_session_identity_cache(source_context, change) -> None:
    db, user, _, records = source_context
    assert load(source_context)
    with db.get_bind().begin() as connection:
        if change == "role":
            connection.execute(
                update(Membership)
                .where(Membership.id == records["member"].id)
                .values(role=WorkspaceRole.AUDITOR)
            )
        elif change == "inactive":
            connection.execute(update(User).where(User.id == user.id).values(is_active=False))
        else:
            connection.execute(
                update(DataSource)
                .where(DataSource.id == records["source"].id)
                .values(status=DataSourceStatus.DISABLED)
            )
    with pytest.raises(AdvancedAnalysisError):
        load(source_context)
