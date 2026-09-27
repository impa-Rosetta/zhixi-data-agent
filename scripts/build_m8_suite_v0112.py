"""Freeze source-data numeric boundaries with independent expected calculations."""

import json
from pathlib import Path

from packages.evaluation import load_suite

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.12.json"


def main() -> None:
    previous = load_suite(ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.11.json")
    if previous.published or len(previous.cases) != 69:
        raise ValueError("Frozen baseline changed")
    document = previous.model_dump(mode="json")
    for key, value, reason in (
        ("zero-defects", "0", "零缺陷与零分母区别"),
        ("all-defective", "100", "全部缺陷的100%边界"),
        ("tiny-rate", "0.000001", "极小比例不得整数截断"),
        ("large-volume", "25", "超过32位整数的合成生产量"),
        ("weighted-batches", "1", "不等批量必须比值汇总而不是平均批次比例"),
        ("same-timestamp-batches", "5", "同时间不同批次不得误去重"),
        ("exclusive-month-end", "2.5", "包含月初、月末且排除下月零点"),
    ):
        document["cases"].append(
            {
                "id": f"anomaly-numeric-{key}",
                "category": "anomaly",
                "turns": ["2026年9月的不良率是多少？"],
                "rationale": f"独立合成源验证{reason}，答案数字必须与真实查询Evidence完全一致。",
                "expected": {
                    "status": "completed",
                    "task_type": "metric_query",
                    "metric_ids": ["defect_rate"],
                    "required_tools": ["query.metric"],
                    "allowed_tools": ["semantic.resolve", "query.metric"],
                    "numbers": {"defect_rate": value},
                    "require_evidence": True,
                },
            }
        )
    document["suite_version"] = "0.1.12"
    with TARGET.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
