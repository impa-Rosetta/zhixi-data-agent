"""Freeze seven semantic-state ambiguity cases without rewriting previous cases."""

import json
from pathlib import Path

from packages.evaluation import load_suite

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.16.json"


def main() -> None:
    previous = load_suite(ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.15.json")
    if previous.published or len(previous.cases) != 92:
        raise ValueError("Frozen baseline changed")
    document = previous.model_dump(mode="json")
    for key, question, reason in (
        ("unknown-quality-metric", "分析综合质量评分", "已有制造口径但未发布该质量指标"),
        ("unknown-production-metric", "分析产能饱和度", "已有制造口径但未发布该生产指标"),
        ("two-defect-definitions", "分析不良率", "两个已发布不良率口径，必须展示准确候选"),
        ("two-inspection-definitions", "分析检验数量", "两个已发布数量口径，必须展示准确候选"),
        ("three-defect-definitions", "分析不良率", "三个口径不得任意挑选或漏掉候选"),
        ("draft-only-definition", "分析不良率", "只有未激活草稿，不得用草稿回答"),
        ("foreign-definition", "分析不良率", "口径仅在其他工作空间，不得绑定或泄露候选"),
    ):
        document["cases"].append(
            {
                "id": f"ambiguity-{key}",
                "category": "ambiguity",
                "turns": [question],
                "rationale": reason
                + "；真实Agent语义加载与持久化自然追问，工具/产物/证据无副作用。",
                "expected": {
                    "status": "clarification",
                    "allowed_tools": [],
                    "require_evidence": False,
                },
            }
        )
    document["suite_version"] = "0.1.16"
    with TARGET.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
