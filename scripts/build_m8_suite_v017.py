"""Freeze model-response failure scenarios without modifying earlier drafts."""

import json
from pathlib import Path

from packages.evaluation import load_suite

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.7.json"


def main() -> None:
    old = load_suite(ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.6.json")
    if old.suite_version != "0.1.6" or old.published or len(old.cases) != 34:
        raise ValueError("Frozen baseline changed")
    document = old.model_dump(mode="json")
    for case_id, reason in (
        ("empty-output", "模型响应没有结构化内容"),
        ("broken-json", "模型响应为损坏的 JSON"),
        ("forbidden-field", "模型意图夹带协议不允许的 SQL 字段"),
    ):
        document["cases"].append(
            {
                "id": f"anomaly-model-{case_id}",
                "category": "anomaly",
                "turns": ["分析不良率"],
                "rationale": f"{reason}；真实运行应失败并自然说明，不执行工具、不产生证据或可信结论。",  # noqa: E501
                "expected": {
                    "status": "failed",
                    "allowed_tools": [],
                    "numbers": {},
                    "require_evidence": False,
                },
            }
        )
    document["suite_version"] = "0.1.7"
    with TARGET.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
