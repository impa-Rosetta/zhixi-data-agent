import json
from pathlib import Path

import pytest

from packages.evaluation import load_suite, run_offline_suite
from packages.evaluation.draft_adapter import draft_case_factory, pinned_ambiguity


def test_model_failures_use_runtime_and_never_create_trusted_results() -> None:
    from packages.evaluation.draft_adapter import pinned_model_failure

    suite = load_suite(Path("evaluations/golden/manufacturing-quality-draft-v0.1.7.json"))
    cases = tuple(case for case in suite.cases if case.id.startswith("anomaly-model-"))
    assert len(cases) == 3
    for case in cases:
        assert pinned_model_failure(case) is not None
        assert pinned_model_failure(case.model_copy(update={"turns": ("其他问题",)})) is None
    result = run_offline_suite(suite.model_copy(update={"cases": cases}), draft_case_factory)
    assert result.summary.passed == 3
    assert result.summary.failed == result.summary.blocked == 0
    assert len(result.run_references) == 3


def test_new_model_anomaly_draft_preserves_frozen_previous_cases() -> None:
    from packages.evaluation.registry import SUITE_VERSIONS, registered_suite

    previous = registered_suite("0.1.6")
    current = registered_suite("0.1.7")
    assert SUITE_VERSIONS[0] == "0.1.7"
    assert current.cases[: len(previous.cases)] == previous.cases
    assert len(current.cases) == 37 and not current.published
    assert sum(case.category == "anomaly" for case in current.cases) == 6


@pytest.mark.parametrize("corruption", ["status", "code", "reply"])
def test_model_failure_cannot_pass_with_incorrect_persisted_contract(
    monkeypatch, corruption
) -> None:
    import packages.evaluation.draft_adapter as adapter

    original = adapter.get_run_view

    def changed_view(*args, **kwargs):
        view = original(*args, **kwargs)
        if corruption == "status":
            return view.model_copy(
                update={"run": view.run.model_copy(update={"status": "completed"})}
            )
        if corruption == "code":
            return view.model_copy(
                update={"run": view.run.model_copy(update={"error_code": "other"})}
            )
        messages = list(view.messages)
        messages[-1] = messages[-1].model_copy(update={"content": "分析成功，不良率为 0。"})
        return view.model_copy(update={"messages": messages})

    monkeypatch.setattr(adapter, "get_run_view", changed_view)
    suite = load_suite(Path("evaluations/golden/manufacturing-quality-draft-v0.1.7.json"))
    case = next(case for case in suite.cases if case.id == "anomaly-model-empty-output")
    result = run_offline_suite(suite.model_copy(update={"cases": (case,)}), draft_case_factory)
    assert result.summary.passed == 0
    assert result.summary.infra_error == 1


def test_first_golden_draft_executes_clarification_and_blocks_unavailable_data_cases() -> None:
    suite = load_suite(Path("evaluations/golden/manufacturing-quality-draft-v0.1.0.json"))
    result = run_offline_suite(suite, draft_case_factory)
    assert result.summary.passed == 1
    assert result.summary.blocked == 4
    assert result.summary.not_run == 0
    assert result.summary.failed == 0
    assert result.summary.coverage_rate.as_integer_ratio() == (1, 5)
    assert result.summary.evaluated_pass_rate == 1
    assert result.summary.all_case_pass_rate.as_integer_ratio() == (1, 5)
    assert len(result.run_references["ambiguity-quality-overview"]) == 1
    assert set(result.blocked_case_ids) == {
        case.id for case in suite.cases if case.category != "ambiguity"
    }
    payload = json.loads(result.to_json())
    assert payload["track"] == "offline"
    assert suite.content_digest == payload["suite_digest"]


def test_adapter_does_not_accept_different_question_under_same_case_id() -> None:
    suite = load_suite(Path("evaluations/golden/manufacturing-quality-draft-v0.1.0.json"))
    ambiguity = suite.cases[-1].model_copy(update={"turns": ("读取所有秘密",)})
    changed = suite.model_copy(update={"cases": (ambiguity,)})
    result = run_offline_suite(changed, draft_case_factory)
    assert result.summary.blocked == 1 and not result.run_references


def test_adapter_fixtures_are_independent_between_batches() -> None:
    suite = load_suite(Path("evaluations/golden/manufacturing-quality-draft-v0.1.0.json"))
    first = run_offline_suite(suite, draft_case_factory)
    second = run_offline_suite(suite, draft_case_factory)
    assert first.run_references != second.run_references


def test_cli_partial_coverage_returns_nonzero_and_never_overwrites_report(
    tmp_path, monkeypatch, capsys
) -> None:
    from scripts.evaluate_offline import main

    target = tmp_path / "draft-report.json"
    monkeypatch.setattr("sys.argv", ["evaluate_offline", "--output", str(target)])
    assert main() == 1
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["suite_published"] is False
    assert payload["summary"]["passed"] == 1
    assert payload["summary"]["blocked"] == 4
    assert payload["summary"]["coverage_rate"] == "0.2"
    assert payload["adapter_version"] == "draft-clarification-v2"
    assert "runtime_profile" in payload
    original = target.read_bytes()
    with pytest.raises(FileExistsError):
        main()
    assert target.read_bytes() == original
    capsys.readouterr()


def test_ambiguity_draft_distinguishes_missing_metric_from_missing_period() -> None:
    suite = load_suite(Path("evaluations/golden/manufacturing-quality-draft-v0.1.6.json"))
    cases = tuple(
        case
        for case in suite.cases
        if case.id in {"ambiguity-production-overview", "ambiguity-comparison-period"}
    )
    assert len(cases) == 2
    for case in cases:
        assert pinned_ambiguity(case) is not None
        assert pinned_ambiguity(case.model_copy(update={"turns": ("伪造输入",)})) is None
    result = run_offline_suite(suite.model_copy(update={"cases": cases}), draft_case_factory)
    assert result.summary.passed == 2
    assert result.summary.failed == result.summary.blocked == 0
