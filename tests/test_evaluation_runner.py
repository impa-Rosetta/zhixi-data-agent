import uuid
from contextlib import contextmanager
from decimal import Decimal

import pytest

from packages.evaluation import EvaluationCase, EvaluationSuite, ObservedOutcome
from packages.evaluation.runner import (
    OfflineCaseExecution,
    OfflineExecutionError,
    run_offline_suite,
)


def _suite() -> EvaluationSuite:
    return EvaluationSuite(
        suite_version="0.1.0",
        synthetic_dataset_id="synthetic-test-v1",
        semantic_version="1",
        cases=tuple(
            EvaluationCase.model_validate(
                {
                    "id": f"standard-case-{index}",
                    "category": "standard",
                    "turns": ["你好"],
                    "rationale": "隔离执行器生命周期回归",
                    "expected": {"status": "completed"},
                }
            )
            for index in range(3)
        ),
    )


def test_offline_runner_isolates_cases_and_serializes_without_raw_observations() -> None:
    lifecycle = []

    @contextmanager
    def factory(case):
        lifecycle.append((case.id, "enter"))

        class Session:
            def execute(self):
                return OfflineCaseExecution(ObservedOutcome(status="completed"))

        try:
            yield Session()
        finally:
            lifecycle.append((case.id, "exit"))

    suite = _suite()
    result = run_offline_suite(suite, factory)
    assert result.summary.passed == 3
    assert result.summary.coverage_rate == Decimal(1)
    assert lifecycle == [(case.id, stage) for case in suite.cases for stage in ("enter", "exit")]
    payload = result.to_json()
    assert suite.content_digest in payload
    assert '"track":"offline"' in payload
    assert "你好" not in payload
    assert result.category_summaries["standard"].total == 3


def test_execution_error_is_sanitized_and_cleanup_still_runs() -> None:
    cleaned = []

    @contextmanager
    def factory(case):
        class Session:
            def execute(self):
                if case.id.endswith("0"):
                    raise RuntimeError("SECRET_SUPPLIER_RESPONSE")
                return OfflineCaseExecution(ObservedOutcome(status="completed"))

        try:
            yield Session()
        finally:
            cleaned.append(case.id)

    result = run_offline_suite(_suite(), factory)
    assert len(cleaned) == 3
    assert result.summary.infra_error == 1
    assert result.summary.passed == 2
    assert "SECRET_SUPPLIER_RESPONSE" not in result.to_json()


def test_cleanup_failure_stops_batch_and_does_not_count_a_pass() -> None:
    @contextmanager
    def factory(case):
        class Session:
            def execute(self):
                return OfflineCaseExecution(ObservedOutcome(status="completed"))

        yield Session()
        raise RuntimeError("cleanup secret")

    result = run_offline_suite(_suite(), factory)
    assert result.summary.passed == 0
    assert result.summary.infra_error == 1
    assert result.summary.not_run == 2
    assert result.stopped_reason == "evaluation.cleanup_failed"


def test_explicit_blocked_case_does_not_count_as_evaluated() -> None:
    @contextmanager
    def factory(case):
        class Session:
            def execute(self):
                raise OfflineExecutionError("evaluation.precondition_failed", blocked=True)

        yield Session()

    result = run_offline_suite(_suite(), factory)
    assert result.summary.blocked == 3
    assert result.summary.coverage_rate == Decimal(0)
    assert result.summary.evaluated_pass_rate is None


def test_unknown_subset_is_rejected_before_fixture_is_created() -> None:
    def factory(case):
        raise AssertionError("must not execute")

    with pytest.raises(ValueError, match="unknown"):
        run_offline_suite(_suite(), factory, case_ids=frozenset({"missing-case"}))


def test_run_reuse_is_detected_and_stops_remaining_cases() -> None:
    shared_id = uuid.uuid4()

    @contextmanager
    def factory(case):
        class Session:
            def execute(self):
                return OfflineCaseExecution(ObservedOutcome(status="completed"), (shared_id,))

        yield Session()

    result = run_offline_suite(_suite(), factory)
    assert result.summary.passed == 1
    assert result.summary.infra_error == 1
    assert result.summary.not_run == 1
    assert result.stopped_reason == "evaluation.case_isolation_failed"


def test_case_subset_keeps_full_suite_denominator() -> None:
    @contextmanager
    def factory(case):
        class Session:
            def execute(self):
                return OfflineCaseExecution(ObservedOutcome(status="completed"))

        yield Session()

    result = run_offline_suite(_suite(), factory, case_ids=frozenset({"standard-case-1"}))
    assert result.summary.passed == 1
    assert result.summary.not_run == 2
    assert result.summary.coverage_rate == Decimal(1) / Decimal(3)


def test_adapter_cannot_rewrite_case_expectation_to_make_it_pass() -> None:
    suite = _suite()
    case = suite.cases[0].model_copy(
        update={
            "expected": suite.cases[0].expected.model_copy(
                update={"numbers": {"result": Decimal(12)}}
            )
        }
    )
    suite = suite.model_copy(update={"cases": (case,)})

    @contextmanager
    def factory(copy):
        copy.expected.numbers.clear()

        class Session:
            def execute(self):
                return OfflineCaseExecution(ObservedOutcome(status="completed"))

        yield Session()

    result = run_offline_suite(suite, factory)
    assert result.summary.failed == 1
    assert suite.cases[0].expected.numbers == {"result": Decimal(12)}


def test_fixture_failure_stops_before_execution_without_leaking_details() -> None:
    @contextmanager
    def factory(case):
        raise RuntimeError("SECRET_DATABASE_ADDRESS")
        yield

    result = run_offline_suite(_suite(), factory)
    assert result.summary.infra_error == 1 and result.summary.not_run == 2
    assert result.stopped_reason == "evaluation.fixture_unavailable"
    assert "SECRET_DATABASE_ADDRESS" not in result.to_json()


def test_observation_error_code_is_not_exported_verbatim() -> None:
    @contextmanager
    def factory(case):
        class Session:
            def execute(self):
                return OfflineCaseExecution(
                    ObservedOutcome(status="failed", infra_error_code="SECRET_PROVIDER_RESPONSE")
                )

        yield Session()

    result = run_offline_suite(_suite(), factory)
    assert result.summary.infra_error == 3
    assert result.summary.evaluated_pass_rate is None
    assert "SECRET_PROVIDER_RESPONSE" not in result.to_json()


def test_security_subtypes_are_separate_and_missing_proof_is_not_a_pass() -> None:
    base = _suite()
    cases = tuple(
        EvaluationCase.model_validate(
            {
                "id": f"security-{kind}",
                "category": "security",
                "probe_kind": kind,
                "turns": ["合成安全测试"],
                "rationale": "分轨汇总缺少安全证明的案例",
                "expected": {
                    "status": "denied",
                    "safety_kind": "unauthorized_access",
                    **(
                        {
                            "safety_entrypoint": "api.authorization",
                            "safety_gate_codes": ["http.forbidden"],
                        }
                        if kind == "system_gate"
                        else {}
                    ),
                },
            }
        )
        for kind in ("system_gate", "agent_behavior")
    )
    suite = base.model_copy(update={"cases": cases})

    @contextmanager
    def factory(case):
        class Session:
            def execute(self):
                return OfflineCaseExecution(ObservedOutcome(status="denied", policy_denied=True))

        yield Session()

    result = run_offline_suite(suite, factory)
    assert result.summary.failed == 2
    assert set(result.safety_failure_ids) == {case.id for case in cases}
    assert result.safety_summaries["system_gate"].failed == 1
    assert result.safety_summaries["agent_behavior"].failed == 1
