from decimal import Decimal
from types import SimpleNamespace

import pytest

from packages.evaluation.quality_metric_fixture import (
    QUALITY_ROWS,
    QualityMetricSpec,
    create_quality_fixture,
    pinned_quality_metric,
)
from packages.evaluation.registry import registered_suite


def test_quality_metric_suite_preserves_history_and_has_independent_arithmetic() -> None:
    previous = registered_suite("0.1.16")
    suite = registered_suite("0.1.17")
    assert suite.cases[:99] == previous.cases
    assert len(suite.cases) == 123 and not suite.published
    for case in suite.cases[99:]:
        spec = pinned_quality_metric(case)
        assert spec is not None
        assert not pinned_quality_metric(case.model_copy(update={"turns": ("伪造问题",)}))
        assert not pinned_quality_metric(case.model_copy(update={"category": "anomaly"}))
        changed = case.model_copy(
            update={"expected": case.expected.model_copy(update={"numbers": {}})}
        )
        assert pinned_quality_metric(changed) == spec
        totals = tuple(map(sum, zip(*QUALITY_ROWS[spec.month_key], strict=True)))
        inspected, qualified, defect, scrap, rework, first_pass = map(Decimal, totals)
        oracle = {
            "qualified_quantity": qualified,
            "scrap_quantity": scrap,
            "rework_quantity": rework,
            "first_pass_yield": first_pass / inspected * 100,
            "scrap_rate": scrap / inspected * 100,
            "rework_rate": rework / inspected * 100,
            "inspection_pass_rate": qualified / inspected * 100,
            "defect_ppm": defect / inspected * 1000000,
        }
        key = case.expected.metric_ids[0]
        assert case.expected.numbers == {key: oracle[key]}


@pytest.mark.parametrize("schema", ["public", "eval_other", 'eval_";DROP SCHEMA public;--'])
def test_quality_fixture_refuses_unowned_target_before_writing(schema) -> None:
    def unexpected_write(*args):
        pytest.fail("Unowned schema must not reach the database")

    with pytest.raises(ValueError, match="evaluation.invalid_fixture_schema"):
        create_quality_fixture(
            SimpleNamespace(execute=unexpected_write),
            schema,
            QualityMetricSpec("july", "2026年7月", "合格数量"),
        )
