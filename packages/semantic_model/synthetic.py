import random
from dataclasses import dataclass
from typing import cast


@dataclass(frozen=True)
class SyntheticManufacturingData:
    variant: str
    tables: dict[str, list[dict[str, object]]]
    expected: dict[str, float]
    anomalies: list[dict[str, object]]


def generate_manufacturing_data(
    seed: int = 2026, variant: str = "standard", rows: int = 30
) -> SyntheticManufacturingData:
    if variant not in {"standard", "renamed", "missing_column"}:
        raise ValueError("variant must be standard, renamed, or missing_column")
    rng = random.Random(seed)
    inspections: list[dict[str, object]] = []
    orders: list[dict[str, object]] = []
    for index in range(rows):
        planned = rng.randint(800, 1200)
        produced = max(0, planned + rng.randint(-100, 60))
        defects = rng.randint(4, 35)
        inspected = produced
        if index == 7:
            defects += 140
        qualified = max(0, inspected - defects)
        orders.append(
            {
                "order_id": f"MO-{index + 1:04d}",
                "planned_quantity": planned,
                "produced_quantity": produced,
                "start_time": f"2026-08-{index % 28 + 1:02d}T08:00:00Z",
            }
        )
        inspections.append(
            {
                "inspection_id": f"QI-{index + 1:04d}",
                "order_id": f"MO-{index + 1:04d}",
                "inspected_quantity": inspected,
                "qualified_quantity": qualified,
                "defect_quantity": defects,
                "scrap_quantity": defects // 5,
                "rework_quantity": defects // 3,
                "first_pass_quantity": max(0, qualified - defects // 4),
                "inspection_time": f"2026-08-{index % 28 + 1:02d}T16:00:00Z",
            }
        )
    if variant == "renamed":
        orders = [
            {
                (
                    "mo_no"
                    if key == "order_id"
                    else "plan_qty"
                    if key == "planned_quantity"
                    else "actual_qty"
                    if key == "produced_quantity"
                    else key
                ): value
                for key, value in row.items()
            }
            for row in orders
        ]
    if variant == "missing_column":
        for row in inspections:
            row.pop("first_pass_quantity")
    total_inspected = sum(float(cast(int, row["inspected_quantity"])) for row in inspections)
    total_defects = sum(float(cast(int, row["defect_quantity"])) for row in inspections)
    expected = {
        "defect_rate": round(total_defects / total_inspected * 100, 6),
        "defect_quantity": total_defects,
        "inspected_quantity": total_inspected,
    }
    anomalies = [
        {"table": "inspection", "row": 7, "metric": "defect_quantity", "kind": "seeded_spike"}
    ]
    return SyntheticManufacturingData(
        variant=variant,
        tables={"production_order": orders, "inspection": inspections},
        expected=expected,
        anomalies=anomalies,
    )
