from decimal import Decimal
from types import SimpleNamespace

import pytest

from packages.evaluation.equipment_metric_fixture import (
    EQUIPMENT_ROWS,
    EquipmentMetricSpec,
    create_equipment_fixture,
    pinned_equipment_metric,
)
from packages.evaluation.registry import registered_suite
from packages.semantic_model.manufacturing import manufacturing_quality_template


def test_equipment_metrics_preserve_history_and_have_independent_source_arithmetic() -> None:
    previous = registered_suite("0.1.17")
    suite = registered_suite("0.1.18")
    assert suite.cases[:123] == previous.cases
    assert len(suite.cases) == 138 and not suite.published
    for case in suite.cases[123:]:
        spec = pinned_equipment_metric(case)
        assert spec is not None
        assert not pinned_equipment_metric(case.model_copy(update={"turns": ("其他问题",)}))
        assert not pinned_equipment_metric(case.model_copy(update={"category": "anomaly"}))
        changed = case.model_copy(
            update={"expected": case.expected.model_copy(update={"numbers": {}})}
        )
        assert pinned_equipment_metric(changed) == spec
        totals = tuple(
            map(sum, zip(*(row[1:] for row in EQUIPMENT_ROWS[spec.variant]), strict=True))
        )
        runtime, planned, downtime, failures, repair, ideal, actual = map(Decimal, totals)
        oracle = {
            "downtime_hours": downtime,
            "failure_count": failures,
            "repair_hours": repair,
            "equipment_availability": runtime / planned * 100,
            "performance_rate": actual / ideal * 100,
        }
        key = case.expected.metric_ids[0]
        assert case.expected.numbers == {key: oracle[key]}
    covered = {
        metric
        for case in suite.cases
        if case.category == "standard"
        for metric in case.expected.metric_ids
    }
    assert covered == {metric.key for metric in manufacturing_quality_template().metrics}


@pytest.mark.parametrize("schema", ["public", "eval_other", 'eval_";DROP SCHEMA public;--'])
def test_equipment_fixture_refuses_unowned_schema_before_writing(schema) -> None:
    def unexpected_write(*args):
        pytest.fail("Unowned schema must not reach the database")

    with pytest.raises(ValueError, match="evaluation.invalid_fixture_schema"):
        create_equipment_fixture(
            SimpleNamespace(execute=unexpected_write),
            schema,
            EquipmentMetricSpec("normal", "停机时长"),
        )
