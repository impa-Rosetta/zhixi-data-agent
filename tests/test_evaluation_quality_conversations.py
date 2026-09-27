from types import SimpleNamespace
from typing import cast

import pytest

from packages.evaluation.postgres_draft_adapter import pinned_multiturn, verify_monthly_result
from packages.evaluation.registry import registered_suite
from packages.shared_contracts.agents import AnalysisRunViewResponse


def test_quality_conversation_suite_preserves_history_and_pins_every_turn() -> None:
    old = registered_suite("0.1.18")
    suite = registered_suite("0.1.19")
    assert suite.cases[:138] == old.cases
    assert len(suite.cases) == 144 and not suite.published
    assert sum(case.category == "multi_turn" for case in suite.cases) == 20
    for case in suite.cases[138:]:
        assert case.category == "multi_turn" and pinned_multiturn(case)
        assert not pinned_multiturn(case.model_copy(update={"turns": tuple(reversed(case.turns))}))


@pytest.mark.parametrize(
    "key,values",
    [
        ("qualified_quantity", ("360", "380", "480")),
        ("first_pass_yield", ("85", "90", "90")),
        ("scrap_rate", ("2", "1", "2")),
        ("rework_rate", ("3", "2", "1")),
        ("inspection_pass_rate", ("90", "95", "96")),
        ("defect_ppm", ("100000", "50000", "40000")),
    ],
)
def test_quality_conversation_oracle_rejects_stale_values_and_months(key, values) -> None:
    summary = {
        "columns": ["inspection_time", key],
        "truncated": False,
        "rows": [
            [f"2026-{month}-01T00:00:00+00:00", value]
            for month, value in zip(("07", "08", "09"), values, strict=True)
        ],
    }
    view = cast(
        AnalysisRunViewResponse,
        SimpleNamespace(artifacts=[SimpleNamespace(artifact_type="query_result", summary=summary)]),
    )
    assert verify_monthly_result(view, key)
    summary["rows"][0][1] = "-999"
    assert not verify_monthly_result(view, key)
    summary["rows"][0][1] = values[0]
    summary["rows"][0][0] = "2026-06-01T00:00:00+00:00"
    assert not verify_monthly_result(view, key)
