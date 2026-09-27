"""Reviewed draft adapter: real clarification path, no synthetic metric executor."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
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
from packages.model_gateway import DeepSeekGateway, FakeGateway, GatewayResponse, GatewayUsage
from packages.platform_core.database import Base
from packages.platform_core.models import User, Workspace
from packages.shared_contracts.agents import CreateAnalysisRunRequest

ADAPTER_VERSION = "draft-clarification-v3"
AMBIGUITY_CASES = {
    "ambiguity-quality-overview": ("看看质量情况", "metric_query", (), "metric_required"),
    "ambiguity-production-overview": ("看看生产情况", "metric_query", (), "metric_required"),
    "ambiguity-trend-metric": ("看看最近三个月的趋势", "trend", (), "metric_required"),
    "ambiguity-ranking-metric": ("哪些工单排名最高？", "ranking", (), "metric_required"),
    "ambiguity-comparison-current-period": (
        "不良率与上月对比",
        "comparison",
        ("不良率",),
        "comparison_period_required",
    ),
    "ambiguity-comparison-baseline-period": (
        "比较本月不良率",
        "comparison",
        ("不良率",),
        "comparison_period_required",
    ),
    "ambiguity-comparison-period": (
        "对比一下不良率",
        "comparison",
        ("不良率",),
        "comparison_period_required",
    ),
}

# Independent fixture inputs: only the absent period should be requested.
_COMPARISON_PERIODS = {
    "ambiguity-comparison-current-period": (None, "previous_period"),
    "ambiguity-comparison-baseline-period": ("this_month", None),
}

MODEL_FAILURE_CASES: dict[str, tuple[str, str | None, str]] = {
    "anomaly-model-empty-output": ("分析不良率", None, "model.missing_structured_output"),
    "anomaly-model-broken-json": ("分析不良率", '{"task_type":', "model.schema_validation_failed"),
    "anomaly-model-forbidden-field": (
        "分析不良率",
        '{"task_type":"metric_query","goal":"分析不良率","metrics":["不良率"],"sql":"SELECT 1"}',
        "model.schema_validation_failed",
    ),
}

# HTTP transport is synthetic; parsing, retry policy and Agent persistence are real.
PROVIDER_FAILURE_CASES: dict[str, tuple[str, str, bool]] = {
    "timeout": ("timeout", "model.network_error", True),
    "connection": ("connection", "model.network_error", True),
    "rate-limit": ("429", "model.rate_limited", True),
    "unavailable": ("503", "model.provider_unavailable", True),
    "authentication": ("401", "model.authentication_failed", False),
    "rejected": ("400", "model.request_rejected", False),
    "invalid-response": ("200", "model.invalid_response", False),
}


def pinned_provider_failure(case: EvaluationCase) -> tuple[str, str, bool] | None:
    spec = PROVIDER_FAILURE_CASES.get(case.id.removeprefix("anomaly-provider-"))
    return (
        spec
        if (
            case.id.startswith("anomaly-provider-")
            and case.category == "anomaly"
            and case.turns == ("分析不良率",)
        )
        else None
    )


class _ProviderFailureSession:
    def __init__(self, db: Session, user: User, workspace: Workspace, case: EvaluationCase) -> None:
        self.db, self.user, self.workspace, self.case = db, user, workspace, case

    def execute(self) -> OfflineCaseExecution:
        spec = pinned_provider_failure(self.case)
        if spec is None:
            raise OfflineExecutionError("evaluation.precondition_failed", blocked=True)
        fault, code, retryable = spec
        attempts: list[httpx.Request] = []
        canary = "SYNTHETIC_PROVIDER_BODY_CANARY"

        def transport(request: httpx.Request) -> httpx.Response:
            attempts.append(request)
            if request.url.host != "provider.example.invalid":
                raise OfflineExecutionError("evaluation.fixture_unavailable")
            if fault == "timeout":
                raise httpx.ReadTimeout(canary, request=request)
            if fault == "connection":
                raise httpx.ConnectError(canary, request=request)
            return httpx.Response(int(fault), json={"provider_debug": canary}, request=request)

        run = create_run(
            self.db,
            workspace_id=self.workspace.id,
            actor_user_id=self.user.id,
            idempotency_key=self.case.id,
            payload=CreateAnalysisRunRequest(message=self.case.turns[0]),
        )
        with httpx.Client(transport=httpx.MockTransport(transport)) as client:
            gateway = DeepSeekGateway(
                api_key="SYNTHETIC_MODEL_KEY_CANARY",
                base_url="https://provider.example.invalid",
                max_attempts=2,
                client=client,
            )
            run_analysis(self.db, run_id=run.id, gateway=gateway)
        view = get_run_view(self.db, workspace_id=self.workspace.id, run_id=run.id)
        last = view.messages[-1] if view.messages else None
        interaction = last.context_patch.get("interaction") if last else None
        safe = (
            view.run.status == ("failed_retryable" if retryable else "failed")
            and view.run.error_code == code
            and len(attempts) == (2 if retryable else 1)
            and not view.tool_calls
            and not view.artifacts
            and not view.evidence
            and not view.validations
            and last is not None
            and last.role == "assistant"
            and isinstance(interaction, dict)
            and interaction.get("kind") == "error"
            and interaction.get("retryable") is retryable
            and ("请稍后重新尝试" if retryable else "没有产生可用结论") in last.content
            and "model." not in last.content
            and canary not in view.model_dump_json()
            and "SYNTHETIC_MODEL_KEY_CANARY" not in view.model_dump_json()
            and (
                code not in {"model.authentication_failed", "model.request_rejected"}
                or "管理员" in last.content
            )
        )
        if not safe:
            raise OfflineExecutionError("evaluation.execution_failed")
        return OfflineCaseExecution(ObservedOutcome(status="failed"), (run.id,))


def pinned_model_failure(case: EvaluationCase) -> tuple[str, str | None, str] | None:
    spec = MODEL_FAILURE_CASES.get(case.id)
    return spec if spec and case.category == "anomaly" and case.turns == (spec[0],) else None


class _ModelFailureSession:
    def __init__(self, db: Session, user: User, workspace: Workspace, case: EvaluationCase) -> None:
        self.db, self.user, self.workspace, self.case = db, user, workspace, case

    def execute(self) -> OfflineCaseExecution:
        spec = pinned_model_failure(self.case)
        if spec is None:
            raise OfflineExecutionError("evaluation.precondition_failed", blocked=True)
        run = create_run(
            self.db,
            workspace_id=self.workspace.id,
            actor_user_id=self.user.id,
            idempotency_key=self.case.id,
            payload=CreateAnalysisRunRequest(message=spec[0]),
        )
        gateway = FakeGateway(
            [
                GatewayResponse(
                    "offline-malformed-1",
                    "fake",
                    spec[1],
                    None,
                    (),
                    "stop",
                    GatewayUsage(20, 10, 30),
                )
            ]
        )
        run_analysis(self.db, run_id=run.id, gateway=gateway)
        view = get_run_view(self.db, workspace_id=self.workspace.id, run_id=run.id)
        last = view.messages[-1] if view.messages else None
        safe_failure = (
            view.run.status == "failed"
            and view.run.error_code == spec[2]
            and len(gateway.calls) == 1
            and not view.tool_calls
            and not view.artifacts
            and not view.evidence
            and not view.validations
            and last is not None
            and last.role == "assistant"
            and "没有产生可用结论" in last.content
            and "model." not in last.content
            and "SELECT" not in last.content
        )
        if not safe_failure:
            raise OfflineExecutionError("evaluation.execution_failed")
        return OfflineCaseExecution(ObservedOutcome(status="failed"), (run.id,))


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
        time_range, comparison = _COMPARISON_PERIODS.get(self.case.id, (None, None))
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
                            "time_range": time_range,
                            "comparison": comparison,
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
        expected_missing = (
            ["metrics"]
            if expected_reason == "metric_required"
            else [
                field
                for field, value in (("time_range", time_range), ("comparison", comparison))
                if value is None
            ]
        )
        expected_question = (
            "你希望分析哪个指标？"
            if expected_reason == "metric_required"
            else "请说明要比较的当前周期和对比周期。"
        )
        if (
            not isinstance(clarification, dict)
            or clarification.get("reason_code") != expected_reason
            or clarification.get("missing_fields") != expected_missing
            or clarification.get("question") != expected_question
            or clarification.get("resume_node")
            != ("understand" if expected_reason == "metric_required" else "route")
        ):
            return OfflineCaseExecution(ObservedOutcome(status="failed"), (run.id,))
        return OfflineCaseExecution(observe_clarification_run(view), (run.id,))


@contextmanager
def draft_case_factory(case: EvaluationCase) -> Iterator[OfflineCaseSession]:
    """Only pinned ambiguity cases are ready; numeric cases need real query fixtures."""
    if (
        pinned_ambiguity(case) is None
        and pinned_model_failure(case) is None
        and pinned_provider_failure(case) is None
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
            if pinned_provider_failure(case) is not None:
                yield _ProviderFailureSession(db, user, workspace, case)
            elif pinned_model_failure(case) is not None:
                yield _ModelFailureSession(db, user, workspace, case)
            else:
                yield _ClarificationSession(db, user, workspace, case)
    finally:
        engine.dispose()
