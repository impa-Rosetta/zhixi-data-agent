"""Freeze same-conversation condition changes with independent PostgreSQL oracles."""

import json
from pathlib import Path

from packages.evaluation import load_suite
from packages.evaluation.postgres_draft_adapter import MULTITURN_CASES

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.10.json"
CASE_IDS = (
    "multiturn-narrow-month",
    "multiturn-replace-month",
    "multiturn-reset-range",
    "multiturn-replace-metric",
    "multiturn-narrow-then-explain",
    "multiturn-replace-metric-retains-month",
    "multiturn-social-retains-narrowed-month",
)


def main() -> None:
    previous = load_suite(ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.9.json")
    if previous.published or len(previous.cases) != 62:
        raise ValueError("Frozen baseline changed")
    document = previous.model_dump(mode="json")
    for case_id in CASE_IDS:
        spec = MULTITURN_CASES[case_id]
        explain = spec.phases[-1] == "explain"
        tools = (
            ["analysis.describe"]
            if explain
            else [
                "semantic.resolve",
                "query.metric",
                "analysis.describe",
                "visualization.compose",
            ]
        )
        metric = "inspected_quantity" if "switch_metric" in spec.phases else "defect_rate"
        document["cases"].append(
            {
                "id": case_id,
                "category": "multi_turn",
                "turns": list(spec.turns),
                "rationale": "同会话修改条件；逐轮核对独立合成数据预期、时间范围和指标，解释只能引用最新已验证结果。",  # noqa: E501
                "expected": {
                    "status": "completed",
                    "task_type": "trend",
                    "metric_ids": [] if explain else [metric],
                    "required_tools": ["analysis.describe"] if explain else tools[1:],
                    "allowed_tools": tools,
                    "numbers": {},
                    "require_evidence": not explain,
                },
            }
        )
    document["suite_version"] = "0.1.10"
    with TARGET.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
