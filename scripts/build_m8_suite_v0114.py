"""Freeze plan-completion-rate business cases against independent source arithmetic."""

import json
from pathlib import Path

from packages.evaluation import load_suite

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.14.json"


def main() -> None:
    previous = load_suite(ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.13.json")
    if previous.published or len(previous.cases) != 80:
        raise ValueError("Frozen baseline changed")
    document = previous.model_dump(mode="json")
    # Source quantities reviewed from source-init.sql, not adapter-produced output.
    for key, month, label, value in (
        ("2025-oct", "2025年10月", "计划达成率", "95.5"),
        ("2025-dec", "2025年12月", "达成率", "96.2"),
        ("2026-jan", "2026年1月", "计划达成率", "95.1"),
        ("2026-mar", "2026年3月", "达成率", "94.4"),
        ("2026-jul", "2026年7月", "计划达成率", "97.2"),
        ("2026-sep", "2026年9月", "达成率", "94.7"),
    ):
        document["cases"].append(
            {
                "id": f"standard-{key}-completion-rate",
                "category": "standard",
                "turns": [f"{month}的{label}是多少？"],
                "rationale": (
                    f"合成源生产工单计划1000件，实际产量/计划产量×100为{value}%；"
                    "跨年月份、别名及证据数字必须一致。"
                ),
                "expected": {
                    "status": "completed",
                    "task_type": "metric_query",
                    "metric_ids": ["plan_completion_rate"],
                    "required_tools": ["query.metric"],
                    "allowed_tools": ["semantic.resolve", "query.metric"],
                    "numbers": {"plan_completion_rate": value},
                    "absolute_tolerance": "0",
                    "require_evidence": True,
                },
            }
        )
    for key, followup in (("monthly", "按月份展开"), ("explain", "解释一下")):
        explaining = key == "explain"
        tools = (
            ["analysis.describe"]
            if explaining
            else ["query.metric", "analysis.describe", "visualization.compose"]
        )
        document["cases"].append(
            {
                "id": f"multiturn-completion-rate-{key}",
                "category": "multi_turn",
                "turns": ["最近三个月计划达成率趋势", followup],
                "rationale": (
                    "同会话首轮真实查询7/8/9月计划达成率97.2%、96.1%、94.7%；"
                    "续问必须保留指标与时间，解释引用已验证结果且不虚构原因。"
                ),
                "expected": {
                    "status": "completed",
                    "task_type": "trend",
                    "metric_ids": [] if explaining else ["plan_completion_rate"],
                    "required_tools": tools,
                    "allowed_tools": tools if explaining else ["semantic.resolve", *tools],
                    "require_evidence": not explaining,
                },
            }
        )
    document["suite_version"] = "0.1.14"
    with TARGET.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
