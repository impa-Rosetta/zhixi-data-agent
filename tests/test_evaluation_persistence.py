import uuid

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from packages.evaluation.persistence import EvaluationCaseResult, EvaluationRun
from packages.platform_core.database import Base
from packages.platform_core.models import User, Workspace
from packages.semantic_model import models as semantic_models  # noqa: F401


def _database() -> tuple[Session, EvaluationRun]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection: object, _: object) -> None:
        connection.execute("PRAGMA foreign_keys=ON")  # type: ignore[attr-defined]

    Base.metadata.create_all(engine)
    db = Session(engine)
    user = User(email="evaluation@example.test", display_name="Fixture", password_hash="fixture")
    workspace = Workspace(name="Synthetic", slug=uuid.uuid4().hex)
    db.add_all([user, workspace])
    db.flush()
    run = EvaluationRun(
        workspace_id=workspace.id,
        created_by_user_id=user.id,
        idempotency_key="fixture",
        suite_version="0.1.2",
        suite_digest="a" * 64,
        dataset_id="synthetic-fixture",
        semantic_version="fixture-v1",
        model_version="offline-fixed-v1",
        tool_version="fixture-v1",
        prompt_version="fixture-v1",
    )
    db.add(run)
    db.commit()
    return db, run


def test_evaluation_defaults_do_not_claim_model_usage() -> None:
    db, run = _database()
    assert run.track == "offline" and run.status == "queued"
    assert run.calls_used == run.tokens_used == run.attempt_count == 0
    assert run.summary == run.budget == {}
    db.close()


def test_evaluation_idempotency_is_workspace_scoped() -> None:
    db, run = _database()
    duplicate = EvaluationRun(
        workspace_id=run.workspace_id,
        created_by_user_id=run.created_by_user_id,
        idempotency_key="fixture",
        suite_version=run.suite_version,
        suite_digest=run.suite_digest,
        dataset_id=run.dataset_id,
        semantic_version=run.semantic_version,
        model_version=run.model_version,
        tool_version=run.tool_version,
        prompt_version=run.prompt_version,
    )
    db.add(duplicate)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.close()


def test_evaluation_case_rejects_cross_workspace_parent() -> None:
    db, run = _database()
    other = Workspace(name="Other", slug=uuid.uuid4().hex)
    db.add(other)
    db.flush()
    db.add(
        EvaluationCaseResult(
            workspace_id=other.id,
            evaluation_run_id=run.id,
            case_id="fixture_case",
            category="standard",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.close()


@pytest.mark.parametrize("status", ["passed", "unknown", "usage_uncertain"])
def test_evaluation_run_rejects_undefined_status(status: str) -> None:
    db, run = _database()
    run.status = status
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.close()


def test_evaluation_usage_cannot_be_negative() -> None:
    db, run = _database()
    run.tokens_used = -1
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.close()
