"""Independent production data confined to an owned evaluation schema."""

import re

from sqlalchemy import Connection, text

from packages.evaluation.contracts import EvaluationCase

PRODUCTION_BOUNDARIES = {
    "weighted-orders": ((5, 10), (900, 990)),
    "over-completion": ((1200, 1000),),
    "zero-actual": ((0, 1000),),
    "zero-plan": ((0, 0),),
}
QUESTION = "2026年9月的计划达成率是多少？"


def pinned_production_boundary(case: EvaluationCase) -> tuple[tuple[int, int], ...] | None:
    if (
        case.id.startswith("anomaly-production-")
        and case.category == "anomaly"
        and case.turns == (QUESTION,)
    ):
        return PRODUCTION_BOUNDARIES.get(case.id.removeprefix("anomaly-production-"))
    return None


def create_production_fixture(
    connection: Connection, schema: str, rows: tuple[tuple[int, int], ...]
) -> None:
    if re.fullmatch(r"eval_[0-9a-f]{32}", schema) is None:
        raise ValueError("evaluation.invalid_fixture_schema")
    connection.execute(
        text(
            f'CREATE TABLE "{schema}".production_orders '
            "(order_no text, completed_quantity bigint, planned_quantity bigint, "
            "started_at timestamptz)"
        )
    )
    connection.execute(
        text(
            f'INSERT INTO "{schema}".production_orders VALUES (:order_no, :actual, :planned, :at)'
        ),
        [
            {
                "order_no": f"SYNTHETIC-{index}",
                "actual": actual,
                "planned": planned,
                "at": "2026-09-05T09:00:00Z",
            }
            for index, (actual, planned) in enumerate(rows)
        ],
    )
    connection.execute(text(f'GRANT SELECT ON "{schema}".production_orders TO zhixi_reader'))
