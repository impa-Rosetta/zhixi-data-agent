"""Current-authorizing adapter from persisted query evidence to training preparation."""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.authorization import authorize
from apps.api.services.advanced_analysis_sources import load_advanced_analysis_input
from packages.agent_core.persistence import AnalysisEvidence
from packages.modeling.data import ModelDataError, VerifiedTrainingSource
from packages.platform_core.models import Membership, User
from packages.platform_core.policy import Action


def load_training_source(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    artifact_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    content_digest: str,
) -> VerifiedTrainingSource:
    """No source DB execution or writes. Recheck permission on every invocation.

    The shared loader validates complete rows, digest, active catalog/semantics,
    workspace, execution and evidence. Model authority is additionally required.
    This adapter does not launch training or grant access to model files.
    """
    user = db.get(User, actor_user_id, populate_existing=True)
    membership = db.scalar(
        select(Membership)
        .where(Membership.workspace_id == workspace_id, Membership.user_id == actor_user_id)
        .execution_options(populate_existing=True)
    )
    if user is None or not user.is_active or membership is None:
        raise ModelDataError("policy.denied")
    try:
        authorize(db, user=user, workspace_id=workspace_id, action=Action.MODEL_TRAIN)
    except HTTPException as exc:
        raise ModelDataError("policy.denied") from exc
    source = load_advanced_analysis_input(
        db, workspace_id=workspace_id, actor_user_id=actor_user_id, artifact_id=artifact_id
    )
    evidence = db.get(AnalysisEvidence, source.evidence_id, populate_existing=True)
    if (
        evidence is None
        or evidence.workspace_id != workspace_id
        or evidence.reference.get("snapshot_ids") != [str(snapshot_id)]
        or source.content_digest != content_digest
    ):
        raise ModelDataError("model.source_mismatch")
    return VerifiedTrainingSource(
        source.artifact_id, snapshot_id, source.evidence_id, source.data, source.content_digest
    )
