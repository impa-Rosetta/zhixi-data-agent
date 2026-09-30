# ruff: noqa: F811 -- imported pytest fixture is intentionally requested by name
import uuid

import pytest
from sqlalchemy import update
from test_advanced_analysis_sources import source_context  # noqa: F401

from apps.api.services.modeling_sources import load_training_source
from packages.modeling.data import ModelDataError
from packages.platform_core.models import (
    DataSource,
    DataSourceStatus,
    Membership,
    User,
    WorkspaceRole,
)
from packages.platform_core.policy import Action, PolicyRequest, is_allowed


def load(context, **updates):
    db, user, workspace, records = context
    return load_training_source(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        artifact_id=records["artifact"].id,
        snapshot_id=updates.get("snapshot_id", records["snapshot"].id),
        content_digest=updates.get("digest", records["artifact"].content_digest),
    )


@pytest.mark.parametrize("role", list(WorkspaceRole))
def test_training_permission_is_distinct_and_current(source_context, role):
    db, _, _, records = source_context
    records["member"].role = role
    db.commit()
    if role == WorkspaceRole.AUDITOR:
        with pytest.raises(ModelDataError, match="policy.denied"):
            load(source_context)
    else:
        source = load(source_context)
        assert source.snapshot_id == records["snapshot"].id
        assert source.evidence_id == records["evidence"].id


@pytest.mark.parametrize("role", list(WorkspaceRole))
@pytest.mark.parametrize("action", [Action.MODEL_READ, Action.MODEL_TRAIN, Action.MODEL_PREDICT])
def test_model_role_matrix(role, action):
    space = uuid.uuid4()
    expected = role != WorkspaceRole.AUDITOR or action == Action.MODEL_READ
    assert is_allowed(PolicyRequest(uuid.uuid4(), space, space, role, action)) == expected
    assert not is_allowed(PolicyRequest(uuid.uuid4(), space, uuid.uuid4(), role, action))


@pytest.mark.parametrize("updates", [{"snapshot_id": uuid.uuid4()}, {"digest": "a" * 64}])
def test_source_references_must_match(source_context, updates):
    with pytest.raises(ModelDataError, match="model.source_mismatch"):
        load(source_context, **updates)


@pytest.mark.parametrize("mutation", ["role", "disable_user", "disable_source"])
def test_external_changes_are_not_hidden_by_cached_session(source_context, mutation):
    db, user, _, records = source_context
    load(source_context)
    with db.get_bind().begin() as connection:
        if mutation == "role":
            connection.execute(
                update(Membership)
                .where(Membership.id == records["member"].id)
                .values(role=WorkspaceRole.AUDITOR)
            )
        elif mutation == "disable_user":
            connection.execute(update(User).where(User.id == user.id).values(is_active=False))
        else:
            connection.execute(
                update(DataSource)
                .where(DataSource.id == records["source"].id)
                .values(status=DataSourceStatus.DISABLED)
            )
    with pytest.raises(ModelDataError):
        load(source_context)


@pytest.mark.parametrize(
    "record,field,value",
    [
        ("artifact", "workspace_id", uuid.uuid4()),
        ("source", "active_snapshot_id", uuid.uuid4()),
        ("artifact", "content_digest", "0" * 64),
        ("validation", "outcome", "failed"),
    ],
)
def test_invalid_provenance_is_rejected(source_context, record, field, value):
    db, _, _, records = source_context
    setattr(records[record], field, value)
    db.commit()
    with pytest.raises(ModelDataError):
        load(source_context)
