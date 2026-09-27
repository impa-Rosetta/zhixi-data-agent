import json
from pathlib import Path

import pytest

from packages.evaluation import load_suite, run_offline_suite
from packages.evaluation.draft_adapter import draft_case_factory, pinned_ambiguity


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
