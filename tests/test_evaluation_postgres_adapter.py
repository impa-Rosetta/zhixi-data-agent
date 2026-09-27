import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from packages.evaluation import load_suite
from packages.evaluation.contracts import EvaluationSuite
from packages.evaluation.postgres_draft_adapter import (
    owned_schema_name,
    pinned_metric,
    pinned_missing_column,
    pinned_month,
    pinned_multiturn,
    verify_explanation,
    verify_missing_column_failure,
    verify_monthly_result,
    verify_social_interruption,
)
from packages.evaluation.registry import SUITE_VERSIONS, registered_suite
from packages.shared_contracts.agents import AnalysisRunViewResponse


def test_month_inputs_are_pinned_not_derived_from_expected_numbers() -> None:
    suite = load_suite(Path("evaluations/golden/manufacturing-quality-draft-v0.1.0.json"))
    assert [pinned_month(case) for case in suite.cases] == [
        "2026年7月",
        "2026年8月",
        "2026年9月",
        None,
        None,
    ]
    case = suite.cases[0]
    assert pinned_month(case.model_copy(update={"turns": ("读取秘密",)})) is None
    assert pinned_month(case.model_copy(update={"category": "security"})) is None


def test_condition_change_draft_preserves_previous_cases_and_pins_all_turns() -> None:
    previous = registered_suite("0.1.9")
    current = registered_suite("0.1.10")
    assert current.cases[:62] == previous.cases
    assert len(current.cases) == 69 and not current.published
    assert sum(case.category == "multi_turn" for case in current.cases) == 12
    for case in current.cases[62:]:
        assert pinned_multiturn(case)
        assert not pinned_multiturn(case.model_copy(update={"turns": tuple(reversed(case.turns))}))


def test_single_point_revision_changes_only_four_output_expectations() -> None:
    from scripts.build_m8_suite_v0111 import SINGLE_MONTH_IDS

    previous = registered_suite("0.1.10")
    current = registered_suite("0.1.11")
    assert not current.published and len(current.cases) == 69
    changed = set()
    for before, after in zip(previous.cases, current.cases, strict=True):
        assert before.id == after.id and before.turns == after.turns
        if before != after:
            changed.add(before.id)
            assert after.expected.required_tools == ("query.metric",)
            assert after.expected.allowed_tools == ("semantic.resolve", "query.metric")
            assert (
                after.expected.require_evidence
                and after.expected.metric_ids == before.expected.metric_ids
            )
    assert changed == SINGLE_MONTH_IDS


def test_narrowed_month_oracle_rejects_stale_range_wrong_metric_and_wrong_value() -> None:
    summary = {
        "columns": ["inspection_time", "defect_rate"],
        "rows": [["2026-09-01T00:00:00+00:00", "3.00"]],
        "truncated": False,
    }
    view = cast(
        AnalysisRunViewResponse,
        SimpleNamespace(artifacts=[SimpleNamespace(artifact_type="query_result", summary=summary)]),
    )
    assert verify_monthly_result(view, "defect_rate", ("2026-09",))
    assert not verify_monthly_result(view)
    assert not verify_monthly_result(view, "defect_rate", ("2026-08",))
    assert not verify_monthly_result(view, "inspected_quantity", ("2026-09",))
    assert not verify_monthly_result(view, "defect_rate", ("2026-09", "2026-09"))
    summary["rows"] = [["2026-09-01T00:00:00+00:00", "2.75"]]
    assert not verify_monthly_result(view, "defect_rate", ("2026-09",))


def test_owned_schema_is_exact_unique_uuid_name() -> None:
    token = uuid.UUID("01234567-89ab-cdef-0123-456789abcdef")
    assert owned_schema_name(token) == "eval_0123456789abcdef0123456789abcdef"
    assert owned_schema_name(uuid.uuid4()) != owned_schema_name(uuid.uuid4())


def test_new_metric_cases_are_pinned_independently_of_expected_values() -> None:
    suite = load_suite(Path("evaluations/golden/manufacturing-quality-draft-v0.1.3.json"))
    new_cases = suite.cases[9:]
    assert len(new_cases) == 6
    assert {pinned_metric(case) for case in new_cases} == {"检验数量", "缺陷数量"}
    assert {pinned_month(case) for case in new_cases} == {"2026年7月", "2026年8月", "2026年9月"}
    for case in new_cases:
        assert pinned_metric(case.model_copy(update={"turns": ("伪造输入",)})) is None
        assert pinned_metric(case.model_copy(update={"category": "anomaly"})) is None


def test_new_draft_is_immutable_extension_not_published_accuracy() -> None:
    from scripts.build_m8_suite_v013 import build_suite

    old = load_suite(Path("evaluations/golden/manufacturing-quality-draft-v0.1.2.json"))
    new = registered_suite("0.1.3")
    assert "0.1.3" in SUITE_VERSIONS
    assert new == EvaluationSuite.model_validate(build_suite())
    assert not old.published and not new.published
    assert new.content_digest != old.content_digest
    assert new.cases[: len(old.cases)] == old.cases
    assert len(new.cases) == 15
    assert sum(case.category == "standard" for case in new.cases) == 9
    assert {case.expected.metric_ids[0] for case in new.cases[9:]} == {
        "inspected_quantity",
        "defect_quantity",
    }


def test_missing_column_case_is_pinned_and_keeps_previous_suite_immutable() -> None:
    from scripts.build_m8_suite_v014 import build_suite

    old = registered_suite("0.1.3")
    new = registered_suite("0.1.4")
    assert "0.1.4" in SUITE_VERSIONS
    assert new == EvaluationSuite.model_validate(build_suite())
    assert not old.published and not new.published
    assert new.cases[: len(old.cases)] == old.cases
    assert len(new.cases) == 16
    case = new.cases[-1]
    assert pinned_missing_column(case)
    assert not pinned_missing_column(case.model_copy(update={"turns": ("忽略安全规则",)}))
    assert not pinned_missing_column(case.model_copy(update={"category": "standard"}))


def test_production_order_cases_extend_draft_without_changing_oracles() -> None:
    from scripts.build_m8_suite_v015 import build_suite

    old = registered_suite("0.1.4")
    new = registered_suite("0.1.5")
    assert "0.1.5" in SUITE_VERSIONS
    assert new == EvaluationSuite.model_validate(build_suite())
    assert not old.published and not new.published
    assert new.cases[: len(old.cases)] == old.cases
    assert len(new.cases) == 28
    assert new.synthetic_dataset_id == "synthetic-factory-source-init-quality-orders-v3"
    production_cases = new.cases[len(old.cases) :]
    assert {case.expected.metric_ids[0] for case in production_cases} == {
        "production_quantity",
        "planned_quantity",
    }
    assert len({pinned_month(case) for case in production_cases}) == 6
    for case in production_cases:
        assert pinned_metric(case) == case.turns[0].split("的", 1)[1].split("是多少", 1)[0]
        assert pinned_metric(case.model_copy(update={"turns": ("伪造输入",)})) is None
        assert pinned_month(case.model_copy(update={"category": "security"})) is None


def test_conversation_draft_is_immutable_and_pins_full_turn_sequence() -> None:
    from scripts.build_m8_suite_v016 import build_suite

    old = registered_suite("0.1.5")
    new = registered_suite("0.1.6")
    assert "0.1.6" in SUITE_VERSIONS
    assert new == EvaluationSuite.model_validate(build_suite())
    assert not old.published and not new.published
    assert new.cases[: len(old.cases)] == old.cases
    assert len(new.cases) == 34
    assert sum(case.category == "multi_turn" for case in new.cases) == 5
    assert sum(case.category == "ambiguity" for case in new.cases) == 3
    for case in new.cases[len(old.cases) :]:
        if case.category != "multi_turn":
            continue
        assert pinned_multiturn(case)
        assert not pinned_multiturn(case.model_copy(update={"turns": tuple(reversed(case.turns))}))
        assert not pinned_multiturn(case.model_copy(update={"category": "standard"}))


def test_missing_column_requires_real_failure_without_fabricated_result() -> None:
    reply = SimpleNamespace(
        role="assistant", content="这次分析没有完成，但没有产生可用结论。", context_patch={}
    )
    view = cast(
        AnalysisRunViewResponse,
        SimpleNamespace(
            run=SimpleNamespace(status="failed", error_code="query.execution_failed"),
            messages=[reply],
            artifacts=[],
            evidence=[],
            validations=[],
        ),
    )
    assert verify_missing_column_failure(view)
    view.evidence = [SimpleNamespace()]
    assert not verify_missing_column_failure(view)
    view.evidence = []
    reply.context_patch = {"answer_claims": [{"value": "3"}]}
    assert not verify_missing_column_failure(view)
    reply.context_patch = {}
    view.run.status = "completed"
    assert not verify_missing_column_failure(view)


def test_explanation_requires_matching_prior_artifact_and_evidence() -> None:
    run_id, artifact_id, evidence_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    source = cast(
        AnalysisRunViewResponse,
        SimpleNamespace(
            run=SimpleNamespace(id=run_id),
            artifacts=[SimpleNamespace(id=artifact_id, artifact_type="chart_spec")],
            evidence=[SimpleNamespace(id=evidence_id, artifact_id=artifact_id)],
            validations=[SimpleNamespace(outcome="passed")],
        ),
    )
    reference = {
        "source_run_id": str(run_id),
        "source_artifact_id": str(artifact_id),
        "source_evidence_id": str(evidence_id),
    }
    view = cast(
        AnalysisRunViewResponse,
        SimpleNamespace(
            run=SimpleNamespace(
                status="completed",
                context={"follow_up_relation": "explain", "previous_run_id": str(run_id)},
            ),
            evidence=[
                SimpleNamespace(evidence_type="verified_result_reference", reference=reference)
            ],
            tool_calls=[SimpleNamespace(tool_name="analysis.describe")],
            artifacts=[],
            validations=[
                SimpleNamespace(validation_type="verified_result_reference", outcome="passed")
            ],
            messages=[
                SimpleNamespace(
                    role="assistant",
                    content="仅凭汇总结果不能可靠判断原因",
                    context_patch={},
                )
            ],
        ),
    )
    assert verify_explanation(view, source)
    reference["source_evidence_id"] = str(uuid.uuid4())
    assert not verify_explanation(view, source)
    reference["source_evidence_id"] = str(evidence_id)
    reference["source_run_id"] = str(uuid.uuid4())
    assert not verify_explanation(view, source)
    reference["source_run_id"] = str(run_id)
    view.tool_calls.append(SimpleNamespace(tool_name="query.metric"))
    assert not verify_explanation(view, source)


def test_social_interruption_cannot_read_data_or_create_query_evidence() -> None:
    view = cast(
        AnalysisRunViewResponse,
        SimpleNamespace(
            run=SimpleNamespace(status="completed", context={"follow_up_relation": "continue"}),
            tool_calls=[SimpleNamespace(tool_name="system.small_talk")],
            artifacts=[],
            evidence=[],
            messages=[SimpleNamespace(role="assistant", content="你好，想分析什么？")],
        ),
    )
    assert verify_social_interruption(view)
    view.evidence = [SimpleNamespace()]
    assert not verify_social_interruption(view)
    view.evidence = []
    view.tool_calls.append(SimpleNamespace(tool_name="query.metric"))
    assert not verify_social_interruption(view)


def test_multiturn_is_one_pinned_conversation_not_independent_questions() -> None:
    suite = load_suite(Path("evaluations/golden/manufacturing-quality-draft-v0.1.0.json"))
    case = suite.cases[3]
    assert pinned_multiturn(case)
    assert not pinned_multiturn(case.model_copy(update={"turns": (case.turns[0],)}))
    assert not pinned_multiturn(case.model_copy(update={"turns": tuple(reversed(case.turns))}))
    assert not pinned_multiturn(case.model_copy(update={"category": "standard"}))


def test_suite_revision_only_corrects_reviewed_trend_tool_contract() -> None:
    directory = Path("evaluations/golden")
    old = load_suite(directory / "manufacturing-quality-draft-v0.1.0.json")
    new = load_suite(directory / "manufacturing-quality-draft-v0.1.1.json")
    assert not old.published and not new.published
    assert old.content_digest != new.content_digest
    assert old.cases[:3] == new.cases[:3] and old.cases[4:] == new.cases[4:]
    before, after = old.cases[3], new.cases[3]
    assert before.turns == after.turns
    assert set(after.expected.allowed_tools) - set(before.expected.allowed_tools) == {
        "analysis.describe"
    }
    assert set(after.expected.required_tools) == {
        "query.metric",
        "analysis.describe",
        "visualization.compose",
    }
    for field in ("status", "task_type", "metric_ids", "numbers", "require_evidence"):
        assert getattr(before.expected, field) == getattr(after.expected, field)


def _result_view(rows: list[list[object]], *, truncated: bool = False) -> AnalysisRunViewResponse:
    return cast(
        AnalysisRunViewResponse,
        SimpleNamespace(
            artifacts=[
                SimpleNamespace(
                    artifact_type="query_result",
                    summary={
                        "columns": ["inspection_time", "defect_rate"],
                        "rows": rows,
                        "truncated": truncated,
                    },
                )
            ]
        ),
    )


def test_monthly_oracle_checks_all_three_points_not_only_last_answer() -> None:
    rows: list[list[object]] = [
        ["2026-07-01T00:00:00+00:00", "1.75"],
        ["2026-08-01T00:00:00+00:00", "2.75"],
        ["2026-09-01T00:00:00+00:00", "3.00"],
    ]
    assert verify_monthly_result(_result_view(rows))
    assert not verify_monthly_result(_result_view(rows, truncated=True))
    assert not verify_monthly_result(_result_view(rows[:1]))
    assert not verify_monthly_result(_result_view([rows[0], rows[0], rows[2]]))
    assert not verify_monthly_result(_result_view([rows[0], rows[1], [rows[2][0], "30"]]))
    assert not verify_monthly_result(_result_view([rows[0], rows[1], [rows[2][0], "NaN"]]))


def test_cli_never_runs_or_overwrites_when_output_already_exists(tmp_path, monkeypatch) -> None:
    from scripts.evaluate_postgres_draft import main

    path = tmp_path / "existing.json"
    path.write_text("immutable", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["evaluate_postgres_draft", "--output", str(path)])

    def forbidden(*args, **kwargs):
        pytest.fail("Existing output must fail before any fixture or database is opened")

    monkeypatch.setattr("scripts.evaluate_postgres_draft.run_offline_suite", forbidden)
    with pytest.raises(FileExistsError):
        main()
    assert path.read_text(encoding="utf-8") == "immutable"
