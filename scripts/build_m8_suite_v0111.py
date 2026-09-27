"""Correct single-point output expectations; retain the failed previous draft intact."""

import json
from pathlib import Path

from packages.evaluation import load_suite

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.11.json"
SINGLE_MONTH_IDS = frozenset(
    {
        "multiturn-narrow-month",
        "multiturn-replace-month",
        "multiturn-replace-metric-retains-month",
        "multiturn-social-retains-narrowed-month",
    }
)


def main() -> None:
    previous = load_suite(ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.10.json")
    if previous.published or len(previous.cases) != 69:
        raise ValueError("Frozen baseline changed")
    document = previous.model_dump(mode="json")
    changed = set()
    for case in document["cases"]:
        if case["id"] in SINGLE_MONTH_IDS:
            case["expected"]["required_tools"] = ["query.metric"]
            case["expected"]["allowed_tools"] = ["semantic.resolve", "query.metric"]
            case["rationale"] += "单月仅一个点，按已批准单行指标卡方案，不生成误导性统计或趋势图。"
            changed.add(case["id"])
    assert changed == SINGLE_MONTH_IDS
    document["suite_version"] = "0.1.11"
    with TARGET.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
