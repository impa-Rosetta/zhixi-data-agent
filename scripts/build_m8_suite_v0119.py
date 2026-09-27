"""Freeze real quality conversations, including narrow-range explanation and social continuity."""

import json
from pathlib import Path

from packages.evaluation import load_suite

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.19.json"


def main() -> None:
    previous = load_suite(ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.18.json")
    if previous.published or len(previous.cases) != 138:
        raise ValueError("Frozen baseline changed")
    document = previous.model_dump(mode="json")
    for key, label, metric, followups, values in (
        ("qualified-monthly", "合格数量", "qualified_quantity", ["按月份展开"], "360、380、480件"),
        ("first-pass-monthly", "一次通过率", "first_pass_yield", ["按月份展开"], "85%、90%、90%"),
        ("scrap-explain", "报废率", "scrap_rate", ["解释一下"], "2%、1%、2%"),
        ("rework-monthly", "返工率", "rework_rate", ["按月份展开"], "3%、2%、1%"),
        (
            "pass-social",
            "检验合格率",
            "inspection_pass_rate",
            ["你好", "按月份展开"],
            "90%、95%、96%",
        ),
        (
            "ppm-narrow-explain",
            "百万件缺陷数",
            "defect_ppm",
            ["只看2026年9月", "解释一下"],
            "100000、50000、40000PPM",
        ),
    ):
        explaining = followups[-1] == "解释一下"
        tools = (
            ["analysis.describe"]
            if explaining
            else ["query.metric", "analysis.describe", "visualization.compose"]
        )
        document["cases"].append(
            {
                "id": f"multiturn-quality-{key}",
                "category": "multi_turn",
                "turns": [f"最近三个月{label}趋势", *followups],
                "rationale": (
                    f"同会话真实合成查询7/8/9月{values}；逐轮保留范围和指标，"
                    "寒暄不查询，解释必须引用最近已验证结果且不捏造原因。"
                ),
                "expected": {
                    "status": "completed",
                    "task_type": "trend",
                    "metric_ids": [] if explaining else [metric],
                    "required_tools": tools,
                    "allowed_tools": tools if explaining else ["semantic.resolve", *tools],
                    "require_evidence": not explaining,
                },
            }
        )
    document["suite_version"] = "0.1.19"
    with TARGET.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
