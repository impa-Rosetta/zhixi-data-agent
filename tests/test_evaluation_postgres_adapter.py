import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from packages.evaluation import load_suite
from packages.evaluation.postgres_draft_adapter import (
    owned_schema_name,
    pinned_month,
    pinned_multiturn,
    verify_monthly_result,
)
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


def test_owned_schema_is_exact_unique_uuid_name() -> None:
    token = uuid.UUID("01234567-89ab-cdef-0123-456789abcdef")
    assert owned_schema_name(token) == "eval_0123456789abcdef0123456789abcdef"
    assert owned_schema_name(uuid.uuid4()) != owned_schema_name(uuid.uuid4())


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
