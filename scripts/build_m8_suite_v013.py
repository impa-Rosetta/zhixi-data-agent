"""Create the immutable 0.1.3 draft from reviewed synthetic source facts."""

from __future__ import annotations

import json
from pathlib import Path

from packages.evaluation import load_suite

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.2.json"
TARGET = ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.3.json"

# Independently checked against infra/postgres/source-init.sql: two 200-piece
# inspections per month; defect counts are 3+4, 5+6, and 8+4.
MONTHS = (
    ("july", "2026年7月", 400, 7),
    ("august", "2026年8月", 400, 11),
    ("september", "2026年9月", 400, 12),
)


def build_suite() -> dict[str, object]:
    old = load_suite(SOURCE)
    if old.suite_version != "0.1.2" or old.published or len(old.cases) != 9:
        raise ValueError("Frozen baseline changed; re-review source first")
    document = old.model_dump(mode="json")
    cases = document["cases"]
    assert isinstance(cases, list)
    for key, month, inspected, defects in MONTHS:
        for metric_key, metric_name, value in (
            ("inspected_quantity", "检验数量", inspected),
            ("defect_quantity", "缺陷数量", defects),
        ):
            cases.append(
                {
                    "id": f"standard-{key}-{metric_key.replace('_', '-')}",
                    "category": "standard",
                    "turns": [f"{month}的{metric_name}是多少？"],
                    "rationale": (
                        f"infra/postgres/source-init.sql 中 {month} 两次质检的"
                        f"{metric_name}合计为 {value} 件；真实查询与证据必须一致。"
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
    document["suite_version"] = "0.1.3"
    document["published"] = False
    return document


def main() -> None:
    document = build_suite()
    # Exclusive creation avoids silently rewriting an already reviewed version.
    with TARGET.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
