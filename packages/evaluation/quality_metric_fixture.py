"""Owned synthetic quality data covering the remaining published quality metrics."""

import re
from dataclasses import dataclass

from sqlalchemy import Connection, text

from packages.evaluation.contracts import EvaluationCase

# inspected, qualified, defect, scrap, rework, first-pass; not derived from expected values.
QUALITY_ROWS = {
    "july": ((100, 90, 10, 2, 3, 85), (300, 270, 30, 6, 9, 255)),
    "august": ((200, 192, 8, 2, 3, 180), (200, 188, 12, 2, 5, 180)),
    "september": ((50, 48, 2, 1, 1, 45), (450, 432, 18, 9, 4, 405)),
}
QUALITY_TERMS = {
    "qualified_quantity": "合格数量",
    "scrap_quantity": "报废数量",
    "rework_quantity": "返工数量",
    "first_pass_yield": "一次通过率",
    "scrap_rate": "报废率",
    "rework_rate": "返工率",
    "inspection_pass_rate": "检验合格率",
    "defect_ppm": "百万件缺陷数",
}
QUALITY_MONTHS = {"july": "2026年7月", "august": "2026年8月", "september": "2026年9月"}
EXTRA_QUALITY_MAPPINGS = tuple(
    ("inspection", "quality_inspections", name, name)
    for name in ("qualified_quantity", "scrap_quantity", "rework_quantity", "first_pass_quantity")
)


@dataclass(frozen=True)
class QualityMetricSpec:
    month_key: str
    time_range: str
    metric_name: str


def pinned_quality_metric(case: EvaluationCase) -> QualityMetricSpec | None:
    if case.category != "standard":
        return None
    for key, month in QUALITY_MONTHS.items():
        for metric, label in QUALITY_TERMS.items():
            if case.id == f"standard-quality-{key}-{metric.replace('_', '-')}" and case.turns == (
                f"{month}的{label}是多少？",
            ):
                return QualityMetricSpec(key, month, label)
    return None


def create_quality_fixture(connection: Connection, schema: str, spec: QualityMetricSpec) -> None:
    if re.fullmatch(r"eval_[0-9a-f]{32}", schema) is None:
        raise ValueError("evaluation.invalid_fixture_schema")
    connection.execute(
        text(
            f'CREATE TABLE "{schema}".quality_inspections '
            "(inspected_quantity bigint, qualified_quantity bigint, defect_quantity bigint, "
            "scrap_quantity bigint, rework_quantity bigint, first_pass_quantity bigint, "
            "inspected_at timestamptz)"
        )
    )
    month = {"july": "07", "august": "08", "september": "09"}[spec.month_key]
    fields = ("inspected", "qualified", "defect", "scrap", "rework", "first_pass")
    connection.execute(
        text(
            f'INSERT INTO "{schema}".quality_inspections VALUES '
            "(:inspected, :qualified, :defect, :scrap, :rework, :first_pass, :at)"
        ),
        [
            {**dict(zip(fields, row, strict=True)), "at": f"2026-{month}-05T09:00:00Z"}
            for row in QUALITY_ROWS[spec.month_key]
        ],
    )
    connection.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO zhixi_reader'))
    connection.execute(text(f'GRANT SELECT ON "{schema}".quality_inspections TO zhixi_reader'))
