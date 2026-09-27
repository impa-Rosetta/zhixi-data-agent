"""Freeze production ratio boundaries without modifying any prior golden case."""

import json
from pathlib import Path

from packages.evaluation import load_suite

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.15.json"


def main() -> None:
    previous = load_suite(ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.14.json")
    if previous.published or len(previous.cases) != 88:
        raise ValueError("Frozen baseline changed")
    document = previous.model_dump(mode="json")
    for key, value, reason in (
        ("weighted-orders", "90.5", "两工单5/10与900/990，应为905/1000×100而非平均比例"),
        ("over-completion", "120", "1200/1000，不得把真实超额完成强行截断到100%"),
        ("zero-actual", "0", "0/1000是有效0%，不得误当不可计算"),
        ("zero-plan", None, "0/0必须无法计算，不能返回0%或捏造原因"),
    ):
        document["cases"].append(
            {
                "id": f"anomaly-production-{key}",
                "category": "anomaly",
                "turns": ["2026年9月的计划达成率是多少？"],
                "rationale": reason
                + "；独立自有合成源、真实目录发布与只读查询及Evidence链路验证。",
                "expected": {
                    "status": "completed",
                    "task_type": "metric_query",
                    "metric_ids": ["plan_completion_rate"],
                    "required_tools": ["query.metric"],
                    "allowed_tools": ["semantic.resolve", "query.metric"],
                    "numbers": {} if value is None else {"plan_completion_rate": value},
                    "absolute_tolerance": "0",
                    "require_evidence": True,
                },
            }
        )
    document["suite_version"] = "0.1.15"
    with TARGET.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
