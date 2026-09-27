"""Optional real PostgreSQL reservation race on an isolated synthetic account."""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from packages.evaluation.model_budget import reserve_call, settle_call
from packages.evaluation.persistence import EvaluationModelCall, EvaluationRun
from packages.model_gateway import ModelGatewayError
from packages.platform_core.models import User, Workspace


def test_postgres_reservations_are_atomic_and_settle_once() -> None:
    url = os.getenv("EVALUATION_BUDGET_POSTGRES_URL")
    if not url:
        pytest.skip("isolated synthetic PostgreSQL URL not provided")
    engine = create_engine(url)
    with Session(engine) as db:
        user = User(
            email=f"budget-{uuid.uuid4().hex}@example.test",
            display_name="Synthetic budget fixture",
            password_hash="not-a-login-account",
        )
        workspace = Workspace(name="Synthetic budget fixture", slug=f"budget-{uuid.uuid4().hex}")
        db.add_all([user, workspace])
        db.flush()
        run = EvaluationRun(
            workspace_id=workspace.id,
            created_by_user_id=user.id,
            idempotency_key="synthetic-race",
            track="live",
            status="running",
            suite_version="0.1.2",
            suite_digest="a" * 64,
            dataset_id="synthetic-budget",
            semantic_version="fixture-v1",
            model_version="deepseek-v4-pro",
            tool_version="fixture-v1",
            prompt_version="fixture-v1",
            budget={"max_calls": 1, "max_tokens": 1000, "max_seconds": 60},
            started_at=datetime.now(UTC),
        )
        db.add(run)
        db.commit()
        ids = (run.id, workspace.id, user.id)
    try:

        def attempt(key: str) -> uuid.UUID | str:
            try:
                return reserve_call(engine, ids[0], key, "a" * 64, 100)
            except ModelGatewayError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, ("first", "second")))
        successful = [result for result in results if isinstance(result, uuid.UUID)]
        assert len(successful) == 1
        assert results.count("evaluation.budget_exceeded") == 1
        with Session(engine) as db:
            saved = db.get(EvaluationRun, ids[0])
            assert saved is not None
            assert saved.calls_reserved == 1 and saved.tokens_reserved == 100
            assert (
                db.scalar(
                    select(EvaluationModelCall.id).where(
                        EvaluationModelCall.evaluation_run_id == ids[0]
                    )
                )
                == successful[0]
            )
        assert settle_call(engine, successful[0], 30)
        assert not settle_call(engine, successful[0], 30)
        with Session(engine) as db:
            saved = db.get(EvaluationRun, ids[0])
            assert saved is not None
            assert (
                saved.calls_used,
                saved.tokens_used,
                saved.calls_reserved,
                saved.tokens_reserved,
            ) == (1, 30, 0, 0)
    finally:
        with Session(engine) as db:
            db.execute(delete(EvaluationRun).where(EvaluationRun.id == ids[0]))
            db.execute(delete(Workspace).where(Workspace.id == ids[1]))
            db.execute(delete(User).where(User.id == ids[2]))
            db.commit()
        engine.dispose()
