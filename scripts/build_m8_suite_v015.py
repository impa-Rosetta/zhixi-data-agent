"""Create the immutable 0.1.5 draft with production-order metric cases."""

from __future__ import annotations

import json
from pathlib import Path

from packages.evaluation import load_suite

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.4.json"
TARGET = ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.5.json"

# Independently checked against public.production_orders in the synthetic
# source database. The adapter pins only user wording and metric names.
MONTHS = (
    ("2025-oct", "2025年10月", "生产产量", "计划产量", 955),
    ("2025-dec", "2025年12月", "实际产量", "计划数量", 962),
    ("2026-jan", "2026年1月", "完工数量", "计划产量", 951),
    ("2026-mar", "2026年3月", "生产产量", "计划数量", 944),
    ("2026-jul", "2026年7月", "实际产量", "计划产量", 972),
    ("2026-sep", "2026年9月", "完工数量", "计划数量", 947),
)


def build_suite() -> dict[str, object]:
    old = load_suite(SOURCE)
    if old.suite_version != "0.1.4" or old.published or len(old.cases) != 16:
        raise ValueError("Frozen baseline changed; re-review source first")
    document = old.model_dump(mode="json")
    cases = document["cases"]
    assert isinstance(cases, list)
    for key, month, production_label, planned_label, production_value in MONTHS:
        for metric_key, label, value in (
            ("production_quantity", production_label, production_value),
            ("planned_quantity", planned_label, 1000),
        ):
            cases.append(
                {
                    "id": f"standard-{key}-{metric_key.replace('_', '-')}",
                    "category": "standard",
                    "turns": [f"{month}的{label}是多少？"],
                    "rationale": (
                        "infra/postgres/source-init.sql 的 public.production_orders 中"
                        f"{month}工单 {label} 合计为 {value} 件；"
                        "生产工单语义映射、真实只读查询与证据必须一致。"
                    ),
                    "expected": {
                        "status": "completed",
                        "task_type": "metric_query",
                        "metric_ids": [metric_key],
                        "required_tools": ["query.metric"],
                        "allowed_tools": ["semantic.resolve", "query.metric"],
                        "numbers": {metric_key: str(value)},
                        "absolute_tolerance": "0",
                        "require_evidence": True,
                    },
                }
            )
    document["suite_version"] = "0.1.5"
    document["synthetic_dataset_id"] = "synthetic-factory-source-init-quality-orders-v3"
    document["published"] = False
    return document


def main() -> None:
    document = build_suite()
    with TARGET.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
