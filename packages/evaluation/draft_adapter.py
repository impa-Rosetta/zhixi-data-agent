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
from packages.evaluation.contracts import EvaluationCase, ObservedOutcome
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

ADAPTER_VERSION = "draft-clarification-v2"
AMBIGUITY_CASES = {
    "ambiguity-quality-overview": ("看看质量情况", "metric_query", (), "metric_required"),
    "ambiguity-production-overview": ("看看生产情况", "metric_query", (), "metric_required"),
    "ambiguity-comparison-period": (
        "对比一下不良率",
        "comparison",
        ("不良率",),
        "comparison_period_required",
    ),
}


def pinned_ambiguity(case: EvaluationCase) -> tuple[str, str, tuple[str, ...], str] | None:
    spec = AMBIGUITY_CASES.get(case.id)
    if spec is None or case.category != "ambiguity" or case.turns != (spec[0],):
        return None
    return spec


class _UnavailableSession:
    def execute(self) -> OfflineCaseExecution:
        raise OfflineExecutionError("evaluation.precondition_failed", blocked=True)


class _ClarificationSession:
    def __init__(self, db: Session, user: User, workspace: Workspace, case: EvaluationCase) -> None:
        self.db, self.user, self.workspace, self.case = db, user, workspace, case

    def execute(self) -> OfflineCaseExecution:
        spec = pinned_ambiguity(self.case)
        if spec is None:
            raise OfflineExecutionError("evaluation.precondition_failed", blocked=True)
        question, task_type, metrics, expected_reason = spec
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
                            "task_type": task_type,
                            "goal": question,
                            "metrics": list(metrics),
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
            return OfflineCaseExecution(ObservedOutcome(status="failed"), (run.id,))
        clarification = view.run.context.get("clarification")
        if (
            not isinstance(clarification, dict)
            or clarification.get("reason_code") != expected_reason
        ):
            return OfflineCaseExecution(ObservedOutcome(status="failed"), (run.id,))
        return OfflineCaseExecution(observe_clarification_run(view), (run.id,))


@contextmanager
def draft_case_factory(case: EvaluationCase) -> Iterator[OfflineCaseSession]:
    """Only pinned ambiguity cases are ready; numeric cases need real query fixtures."""
    if pinned_ambiguity(case) is None:
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
