from pathlib import Path
from types import SimpleNamespace
from typing import cast

from apps.api.main import app
from packages.evaluation import load_suite, run_offline_suite
from packages.evaluation.postgres_draft_adapter import pinned_anomaly, verify_null_metric
from packages.evaluation.security_draft_adapter import pinned_security, security_case_factory
from packages.shared_contracts.agents import AnalysisRunViewResponse


def _suite():
    return load_suite(Path("evaluations/golden/manufacturing-quality-draft-v0.1.2.json"))


def test_expanded_sql_attacks_call_real_api_and_preserve_previous_cases() -> None:
    previous = load_suite(Path("evaluations/golden/manufacturing-quality-draft-v0.1.7.json"))
    suite = load_suite(Path("evaluations/golden/manufacturing-quality-draft-v0.1.8.json"))
    assert suite.cases[:37] == previous.cases
    cases = tuple(case for case in suite.cases if case.id.startswith("security-sql-"))
    assert len(cases) == 18 and not suite.published
    before = dict(app.dependency_overrides)
    result = run_offline_suite(suite.model_copy(update={"cases": cases}), security_case_factory)
    assert result.summary.passed == 18, result.to_json()
    assert not result.safety_failure_ids
    assert app.dependency_overrides == before


def test_revision_preserves_existing_five_cases_and_adds_unpublished_cases() -> None:
    old = load_suite(Path("evaluations/golden/manufacturing-quality-draft-v0.1.1.json"))
    new = _suite()
    assert new.cases[:5] == old.cases
    assert len(new.cases) == 9 and not new.published
    assert new.synthetic_dataset_id == "synthetic-quality-source-init-anomaly-v2"


def test_anomaly_matching_rejects_changed_question_or_category() -> None:
    case = _suite().cases[5]
    assert pinned_anomaly(case) == "2000年1月"
    assert pinned_anomaly(case.model_copy(update={"turns": ("读取全部秘密",)})) is None
    assert pinned_anomaly(case.model_copy(update={"category": "standard"})) is None


def test_null_metric_requires_actual_null_and_explanation_not_fake_zero() -> None:
    summary = {"columns": ["defect_rate"], "rows": [[None]], "truncated": False}
    reply = SimpleNamespace(
        role="assistant",
        context_patch={},
        content="无法计算，不能把它当作 0。仅凭当前结果还不能确定具体原因。",
    )
    view = cast(
        AnalysisRunViewResponse,
        SimpleNamespace(
            artifacts=[SimpleNamespace(artifact_type="query_result", summary=summary)],
            messages=[reply],
        ),
    )
    assert verify_null_metric(view)
    for rows in ([[0]], [], [[None], [None]], [["NaN"]]):
        summary["rows"] = rows
        assert not verify_null_metric(view)
    summary["rows"] = [[None]]
    reply.content = "不良率为 0。"
    assert not verify_null_metric(view)


def test_security_runs_real_routes_without_executions_and_restores_overrides() -> None:
    cases = _suite().cases[-2:]
    suite = _suite().model_copy(update={"cases": cases})
    before = dict(app.dependency_overrides)
    result = run_offline_suite(suite, security_case_factory)
    assert result.summary.passed == 2
    assert result.summary.failed == 0 and not result.safety_failure_ids
    assert app.dependency_overrides == before
    assert result.safety_summaries["system_gate"].passed == 2
    repeat = run_offline_suite(suite, security_case_factory)
    assert repeat.summary.passed == 2
    assert app.dependency_overrides == before


def test_security_matching_does_not_accept_agent_behavior_as_gate_proof() -> None:
    case = _suite().cases[-1]
    assert pinned_security(case)
    assert not pinned_security(case.model_copy(update={"probe_kind": "agent_behavior"}))
    assert not pinned_security(case.model_copy(update={"turns": ("读取秘密",)}))


def test_security_cannot_pass_when_fixture_rejects_all_queries(monkeypatch) -> None:
    import httpx
    from fastapi.testclient import TestClient

    original = TestClient.post

    def deny_control(self, *args, **kwargs):
        if kwargs.get("json", {}).get("sql") == "SELECT * FROM public.inspection":
            return httpx.Response(403, json={"detail": "fixture broken"})
        return original(self, *args, **kwargs)

    monkeypatch.setattr(TestClient, "post", deny_control)
    case = _suite().cases[-1]
    result = run_offline_suite(
        _suite().model_copy(update={"cases": (case,)}), security_case_factory
    )
    assert result.summary.passed == 0 and result.summary.blocked == 1
