"""Independent equipment-event fixtures, confined to an owned synthetic schema."""

import re
from dataclasses import dataclass

from sqlalchemy import Connection, text

from packages.evaluation.contracts import EvaluationCase

# device, runtime, planned hours, downtime, failure count, repair hours, ideal, actual output.
EQUIPMENT_ROWS = {
    "normal": (("EQ-A", 8, 10, 2, 1, 1, 100, 70), ("EQ-B", 19, 20, 1, 2, 2, 300, 270)),
    "skewed": (("EQ-A", 1, 10, 9, 2, 3, 10, 5), ("EQ-B", 80, 90, 10, 3, 7, 90, 70)),
    "idle": (("EQ-A", 0, 10, 10, 0, 0, 100, 0), ("EQ-B", 0, 90, 90, 0, 0, 900, 0)),
}
EQUIPMENT_TERMS = {
    "downtime_hours": "停机时长",
    "failure_count": "故障次数",
    "repair_hours": "维修时长",
    "equipment_availability": "设备可用率",
    "performance_rate": "性能效率",
}
EQUIPMENT_FIELDS = (
    "equipment_id",
    "runtime_hours",
    "planned_hours",
    "downtime_hours",
    "failure_count",
    "repair_hours",
    "ideal_output",
    "actual_output",
)
EXTRA_EQUIPMENT_MAPPINGS = tuple(
    ("equipment_event", "equipment_events", name, name) for name in EQUIPMENT_FIELDS
)


@dataclass(frozen=True)
class EquipmentMetricSpec:
    variant: str
    metric_name: str


def pinned_equipment_metric(case: EvaluationCase) -> EquipmentMetricSpec | None:
    if case.category != "standard":
        return None
    for variant in EQUIPMENT_ROWS:
        for metric, label in EQUIPMENT_TERMS.items():
            if (
                case.id == f"standard-equipment-{variant}-{metric.replace('_', '-')}"
                and case.turns == (f"当前全部设备的{label}是多少？",)
            ):
                return EquipmentMetricSpec(variant, label)
    return None


def create_equipment_fixture(
    connection: Connection, schema: str, spec: EquipmentMetricSpec
) -> None:
    if re.fullmatch(r"eval_[0-9a-f]{32}", schema) is None:
        raise ValueError("evaluation.invalid_fixture_schema")
    # Existing template publication also requires its quality mapping fixture.
    connection.execute(
        text(
            f'CREATE TABLE "{schema}".quality_inspections '
            "(defect_quantity bigint, inspected_quantity bigint, inspected_at timestamptz)"
        )
    )
    connection.execute(
        text(
            f'CREATE TABLE "{schema}".equipment_events '
            "(equipment_id text, runtime_hours bigint, planned_hours bigint, "
            "downtime_hours bigint, "
            "failure_count bigint, repair_hours bigint, ideal_output bigint, actual_output bigint)"
        )
    )
    connection.execute(
        text(
            f'INSERT INTO "{schema}".equipment_events VALUES '
            "(:equipment_id, :runtime_hours, :planned_hours, :downtime_hours, "
            ":failure_count, :repair_hours, :ideal_output, :actual_output)"
        ),
        [dict(zip(EQUIPMENT_FIELDS, row, strict=True)) for row in EQUIPMENT_ROWS[spec.variant]],
    )
    connection.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO zhixi_reader'))
    for table in ("quality_inspections", "equipment_events"):
        connection.execute(text(f'GRANT SELECT ON "{schema}"."{table}" TO zhixi_reader'))
