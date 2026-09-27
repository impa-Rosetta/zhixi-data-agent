"""Create the immutable 0.1.6 draft with real conversation and clarification paths."""

from __future__ import annotations

import json
from pathlib import Path

from packages.evaluation import load_suite

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.5.json"
TARGET = ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.6.json"


def _trend_case(
    case_id: str,
    turns: list[str],
    metric_id: str,
    rationale: str,
) -> dict[str, object]:
    return {
        "id": case_id,
        "category": "multi_turn",
        "turns": turns,
        "rationale": rationale,
        "expected": {
            "status": "completed",
            "task_type": "trend",
            "metric_ids": [metric_id],
            "required_tools": ["query.metric", "analysis.describe", "visualization.compose"],
            "allowed_tools": [
                "semantic.resolve",
                "query.metric",
                "analysis.describe",
                "visualization.compose",
            ],
            "numbers": {},
            "require_evidence": True,
        },
    }


def build_suite() -> dict[str, object]:
    old = load_suite(SOURCE)
    if old.suite_version != "0.1.5" or old.published or len(old.cases) != 28:
        raise ValueError("Frozen baseline changed; re-review source first")
    document = old.model_dump(mode="json")
    cases = document["cases"]
    assert isinstance(cases, list)
    cases.extend(
        [
            _trend_case(
                "multiturn-inspection-count-then-monthly",
                ["最近三个月检验数量趋势", "按月份展开"],
                "inspected_quantity",
                "同一会话续问细化检验数量趋势；两轮都必须保留最近三个月范围"
                "并经真实查询核对每月 400 件。",
            ),
            _trend_case(
                "multiturn-production-count-then-monthly",
                ["最近三个月生产产量趋势", "按月份展开"],
                "production_quantity",
                "同一会话续问细化生产工单趋势；真实源表 2026 年 7/8/9 月分别为 972、961、947 件。",
            ),
            {
                "id": "multiturn-defect-trend-explain",
                "category": "multi_turn",
                "turns": ["最近三个月不良率趋势", "解释一下"],
                "rationale": (
                    "解释续问必须引用同一会话上一轮已验证趋势，不重新查询、"
                    "不把汇总相关性说成原因，也不伪造新证据。"
                ),
                "expected": {
                    "status": "completed",
                    "task_type": "trend",
                    "required_tools": ["analysis.describe"],
                    "allowed_tools": ["analysis.describe"],
                    "numbers": {},
                    "require_evidence": False,
                },
            },
            _trend_case(
                "multiturn-defect-social-then-refine",
                ["最近三个月不良率趋势", "你好", "按月份展开"],
                "defect_rate",
                "在数据追问之间穿插寒暄；中间不得查询数据，第三轮仍须继承同一会话的指标与时间范围。",
            ),
            {
                "id": "ambiguity-production-overview",
                "category": "ambiguity",
                "turns": ["看看生产情况"],
                "rationale": (
                    "缺少计划产量或生产产量等具体指标，" + "Agent 应自然追问指标且不得执行查询。"  # noqa: E501
                ),
                "expected": {
                    "status": "clarification",
                    "allowed_tools": [],
                    "numbers": {},
                    "require_evidence": False,
                },
            },
            {
                "id": "ambiguity-comparison-period",
                "category": "ambiguity",
                "turns": ["对比一下不良率"],
                "rationale": (
                    "已给出指标但未说明当前和对比周期，" + "Agent 应追问周期而不是擅自默认或查询。"  # noqa: E501
                ),
                "expected": {
                    "status": "clarification",
                    "allowed_tools": [],
                    "numbers": {},
                    "require_evidence": False,
                },
            },
        ]
    )
    document["suite_version"] = "0.1.6"
    document["published"] = False
    return document


def main() -> None:
    document = build_suite()
    with TARGET.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
