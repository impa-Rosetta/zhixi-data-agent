"""Reviewed draft adapter: real clarification path, no synthetic metric executor."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.services.analysis_runs import create_run, get_run_view
from apps.worker.analysis_runtime import run_analysis
from packages.evaluation.contracts import EvaluationCase
from packages.evaluation.observation import observe_clarification_run
from packages.evaluation.runner import (
    OfflineCaseExecution,
    OfflineCaseSession,
    OfflineExecutionError,
)
from packages.model_gateway import FakeGateway, GatewayResponse, GatewayUsage
from packages.platform_core.database import Base
from packages.platform_core.models import User, Workspace
from packages.shared_contracts.agents import CreateAnalysisRunRequest

ADAPTER_VERSION = "draft-clarification-v1"
SUPPORTED_CASE_ID = "ambiguity-quality-overview"
SUPPORTED_TURNS = ("看看质量情况",)


class _UnavailableSession:
    def execute(self) -> OfflineCaseExecution:
        raise OfflineExecutionError("evaluation.precondition_failed", blocked=True)


class _ClarificationSession:
    def __init__(self, db: Session, user: User, workspace: Workspace, case: EvaluationCase) -> None:
        self.db, self.user, self.workspace, self.case = db, user, workspace, case

    def execute(self) -> OfflineCaseExecution:
        run = create_run(
            self.db,
            workspace_id=self.workspace.id,
            actor_user_id=self.user.id,
            idempotency_key=self.case.id,
            payload=CreateAnalysisRunRequest(message=self.case.turns[0]),
        )
        # Fixed model response, not generated from the case's expected result.
        gateway = FakeGateway(
            [
                GatewayResponse(
                    "offline-clarification-1",
                    "fake",
                    json.dumps(
                        {
                            "domain": "manufacturing_quality",
                            "task_type": "metric_query",
                            "goal": "看看质量情况",
                            "metrics": [],
                            "confidence": 0.4,
                        },
                        ensure_ascii=False,
                    ),
                    None,
                    (),
                    "stop",
                    GatewayUsage(20, 10, 30),
                )
            ]
        )
        run_analysis(self.db, run_id=run.id, gateway=gateway)
        view = get_run_view(self.db, workspace_id=self.workspace.id, run_id=run.id)
        if view.run.status != "waiting_for_clarification":
            from packages.evaluation.contracts import ObservedOutcome

            return OfflineCaseExecution(ObservedOutcome(status="failed"), (run.id,))
        return OfflineCaseExecution(observe_clarification_run(view), (run.id,))


@contextmanager
def draft_case_factory(case: EvaluationCase) -> Iterator[OfflineCaseSession]:
    """Only the pinned ambiguity case is ready; numeric cases need real query fixtures."""
    if (
        case.id != SUPPORTED_CASE_ID
        or case.turns != SUPPORTED_TURNS
        or case.category != "ambiguity"
    ):
        yield _UnavailableSession()
        return
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            user = User(
                email="evaluation@example.test",
                display_name="Synthetic Evaluator",
                password_hash="not-a-login-account",
            )
            workspace = Workspace(
                name="Synthetic Offline Evaluation", slug=f"synthetic-eval-{uuid.uuid4().hex}"
            )
            db.add_all([user, workspace])
            db.commit()
            yield _ClarificationSession(db, user, workspace, case)
    finally:
        engine.dispose()
