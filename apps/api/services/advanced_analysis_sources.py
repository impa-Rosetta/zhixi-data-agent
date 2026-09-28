"""Current authorization and provenance gate for advanced analysis tool inputs."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import NoReturn

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.authorization import authorize
from packages.agent_core.persistence import (
    AnalysisArtifact,
    AnalysisEvidence,
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisValidation,
)
from packages.analysis_engine.advanced import AdvancedAnalysisError
from packages.analysis_engine.tools import VerifiedAnalysisInput
from packages.platform_core.models import (
    CatalogSnapshot,
    DataSource,
    DataSourceStatus,
    Membership,
    SnapshotStatus,
    User,
)
from packages.platform_core.policy import Action
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


def _reject(code: str = "analysis.provenance_invalid") -> NoReturn:
    raise AdvancedAnalysisError(code, "当前数据来源或证据已失效，请重新查询后分析。")


def _digest(value: object) -> str:
    try:
        canonical = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise AdvancedAnalysisError("analysis.invalid_table", "数据内容无法通过校验。") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _uuid(value: object) -> uuid.UUID:
    if not isinstance(value, str):
        _reject()
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise AdvancedAnalysisError(
            "analysis.provenance_invalid", "数据引用无法通过校验。"
        ) from exc


def load_advanced_analysis_input(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    artifact_id: uuid.UUID,
    active_run_id: uuid.UUID | None = None,
) -> VerifiedAnalysisInput:
    """Read a complete trusted query artifact without reconnecting to its DB.

    Query validation expiry limits executing SQL again, not reading a past result.
    Active source/catalog/semantic publication and current membership are rechecked.
    The worker may explicitly allow its own currently running run after query verification.
    This function neither executes queries nor writes artifacts or audit records.
    """
    user = db.get(User, actor_user_id, populate_existing=True)
    membership = db.scalar(
        select(Membership)
        .where(Membership.user_id == actor_user_id, Membership.workspace_id == workspace_id)
        .execution_options(populate_existing=True)
    )
    if user is None or not user.is_active or membership is None:
        raise AdvancedAnalysisError("policy.denied", "当前账号没有执行分析的权限。")
    try:
        authorize(db, user=user, workspace_id=workspace_id, action=Action.ANALYSIS_RUN)
    except HTTPException as exc:
        raise AdvancedAnalysisError("policy.denied", "当前账号没有执行分析的权限。") from exc
    artifact = db.scalar(
        select(AnalysisArtifact)
        .where(
            AnalysisArtifact.id == artifact_id,
            AnalysisArtifact.workspace_id == workspace_id,
            AnalysisArtifact.artifact_type == "query_result",
        )
        .execution_options(populate_existing=True)
    )
    if artifact is None:
        _reject("analysis.source_not_found")
    assert artifact is not None
    run = db.get(AnalysisRun, artifact.run_id, populate_existing=True)
    if run is None or run.workspace_id != workspace_id:
        _reject()
    if run.cancel_requested_at is not None:
        _reject("analysis.source_stale")
    if run.status is not AnalysisRunStatus.COMPLETED and not (
        run.id == active_run_id
        and run.status is AnalysisRunStatus.RUNNING
        and run.created_by_user_id == actor_user_id
    ):
        _reject()
    summary = artifact.summary
    if _digest(summary) != artifact.content_digest:
        _reject("analysis.digest_mismatch")
    execution = db.get(QueryExecution, _uuid(summary.get("execution_id")), populate_existing=True)
    query = db.get(ValidatedQuery, _uuid(summary.get("validated_query_id")), populate_existing=True)
    if (
        execution is None
        or query is None
        or execution.workspace_id != workspace_id
        or query.workspace_id != workspace_id
        or execution.validated_query_id != query.id
        or execution.status is not QueryExecutionStatus.SUCCEEDED
        or query.trust is not QueryTrust.TRUSTED
        or summary.get("trust") != "trusted"
    ):
        _reject()
    assert execution is not None and query is not None
    expected_result = {
        "columns": execution.columns,
        "rows": execution.rows,
        "row_count": execution.row_count,
        "truncated": execution.truncated,
    }
    if any(summary.get(key) != value for key, value in expected_result.items()):
        _reject("analysis.digest_mismatch")
    if execution.truncated or execution.row_count != len(execution.rows):
        _reject("analysis.incomplete_data")
    if _digest({"columns": execution.columns, "rows": execution.rows}) != execution.result_digest:
        _reject("analysis.digest_mismatch")
    if (
        not execution.evidence_digest
        or _digest(execution.evidence) != execution.evidence_digest
        or summary.get("evidence_digest") != execution.evidence_digest
    ):
        _reject("analysis.digest_mismatch")
    expected_evidence = {
        "validated_query_id": str(query.id),
        "query_digest": query.digest,
        "result_digest": execution.result_digest,
        "snapshot_id": str(query.snapshot_id),
        "semantic_version_id": str(query.semantic_version_id),
        "dependencies": query.dependencies,
        "trust": "trusted",
    }
    if any(execution.evidence.get(key) != value for key, value in expected_evidence.items()):
        _reject()
    source, snapshot = (
        db.get(DataSource, query.data_source_id, populate_existing=True),
        db.get(CatalogSnapshot, query.snapshot_id, populate_existing=True),
    )
    if (
        source is None
        or snapshot is None
        or source.workspace_id != workspace_id
        or source.deleted_at is not None
        or source.status not in {DataSourceStatus.READY, DataSourceStatus.DEGRADED}
        or source.active_snapshot_id != snapshot.id
        or snapshot.workspace_id != workspace_id
        or snapshot.data_source_id != source.id
        or snapshot.status is not SnapshotStatus.PUBLISHED
    ):
        _reject("analysis.source_stale")
    if query.semantic_model_id is None or query.semantic_version_id is None:
        _reject()
    model = db.get(SemanticModel, query.semantic_model_id, populate_existing=True)
    version = db.get(SemanticModelVersion, query.semantic_version_id, populate_existing=True)
    if (
        model is None
        or version is None
        or model.workspace_id != workspace_id
        or model.status is not SemanticModelStatus.PUBLISHED
        or model.active_version_id != version.id
        or version.workspace_id != workspace_id
        or version.semantic_model_id != model.id
        or version.status is not SemanticVersionStatus.PUBLISHED
    ):
        _reject("analysis.source_stale")
    evidence = db.scalar(
        select(AnalysisEvidence)
        .where(
            AnalysisEvidence.workspace_id == workspace_id,
            AnalysisEvidence.run_id == run.id,
            AnalysisEvidence.artifact_id == artifact.id,
            AnalysisEvidence.evidence_type == "query_execution",
        )
        .execution_options(populate_existing=True)
    )
    validation = db.scalar(
        select(AnalysisValidation.id).where(
            AnalysisValidation.workspace_id == workspace_id,
            AnalysisValidation.run_id == run.id,
            AnalysisValidation.validation_type == "evidence",
            AnalysisValidation.outcome == "passed",
        )
    )
    if (
        evidence is None
        or validation is None
        or evidence.evidence_digest != execution.evidence_digest
        or evidence.reference.get("execution_id") != str(execution.id)
        or evidence.reference.get("validated_query_id") != str(query.id)
        or evidence.reference.get("semantic_version_id") != str(version.id)
        or evidence.reference.get("snapshot_ids") != [str(query.snapshot_id)]
        or evidence.reference.get("trust") != "trusted"
    ):
        _reject()
    assert evidence is not None
    return VerifiedAnalysisInput(artifact.id, evidence.id, dict(summary), artifact.content_digest)
