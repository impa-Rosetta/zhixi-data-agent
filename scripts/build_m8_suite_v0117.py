"""Freeze independent monthly quality counts, percentages and PPM expectations."""

import json
from pathlib import Path

from packages.evaluation import load_suite

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.17.json"


def main() -> None:
    previous = load_suite(ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.16.json")
    if previous.published or len(previous.cases) != 99:
        raise ValueError("Frozen baseline changed")
    document = previous.model_dump(mode="json")
    terms = (
        ("qualified_quantity", "合格数量"),
        ("scrap_quantity", "报废数量"),
        ("rework_quantity", "返工数量"),
        ("first_pass_yield", "一次通过率"),
        ("scrap_rate", "报废率"),
        ("rework_rate", "返工率"),
        ("inspection_pass_rate", "检验合格率"),
        ("defect_ppm", "百万件缺陷数"),
    )
    # Independent reviewed sums/ratios; no import of fixture outputs or source arrays.
    for key, month, values in (
        ("july", "2026年7月", ("360", "8", "12", "85", "2", "3", "90", "100000")),
        ("august", "2026年8月", ("380", "4", "8", "90", "1", "2", "95", "50000")),
        ("september", "2026年9月", ("480", "10", "5", "90", "2", "1", "96", "40000")),
    ):
        for (metric, label), value in zip(terms, values, strict=True):
            document["cases"].append(
                {
                    "id": f"standard-quality-{key}-{metric.replace('_', '-')}",
                    "category": "standard",
                    "turns": [f"{month}的{label}是多少？"],
                    "rationale": (
                        f"独立两批次合成质检数据，{label}汇总为{value}；"
                        "真实映射、聚合、量纲和数字证据一致。"
                    ),
                    "expected": {
                        "status": "completed",
                        "task_type": "metric_query",
                        "metric_ids": [metric],
                        "required_tools": ["query.metric"],
                        "allowed_tools": ["semantic.resolve", "query.metric"],
                        "numbers": {metric: value},
                        "absolute_tolerance": "0",
                        "require_evidence": True,
                    },
                }
            )
    document["suite_version"] = "0.1.17"
    with TARGET.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
