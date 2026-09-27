"""Freeze equipment sums, weighted availability/performance and valid zero results."""

import json
from pathlib import Path

from packages.evaluation import load_suite

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.18.json"


def main() -> None:
    previous = load_suite(ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.17.json")
    if previous.published or len(previous.cases) != 123:
        raise ValueError("Frozen baseline changed")
    document = previous.model_dump(mode="json")
    terms = (
        ("downtime_hours", "停机时长"),
        ("failure_count", "故障次数"),
        ("repair_hours", "维修时长"),
        ("equipment_availability", "设备可用率"),
        ("performance_rate", "性能效率"),
    )
    # Reviewed independent sums, not imported from fixture rows or model-produced output.
    for variant, values in (
        ("normal", ("3", "3", "3", "90", "85")),
        ("skewed", ("19", "5", "10", "81", "75")),
        ("idle", ("100", "0", "0", "0", "0")),
    ):
        for (metric, label), value in zip(terms, values, strict=True):
            document["cases"].append(
                {
                    "id": f"standard-equipment-{variant}-{metric.replace('_', '-')}",
                    "category": "standard",
                    "turns": [f"当前全部设备的{label}是多少？"],
                    "rationale": (
                        f"独立{variant}两设备事件，{label}为{value}；先汇总后相除或求和，"
                        "单位与Evidence一致，不编造时间过滤。"
                    ),
                    "expected": {
                        "status": "completed",
                        "task_type": "metric_query",
                        "metric_ids": [metric],
                        "required_tools": ["query.metric"],
                        "allowed_tools": ["semantic.resolve", "query.metric"],
                        "numbers": {metric: value},
                        "absolute_tolerance": "0",
                        "require_evidence": True,
                    },
                }
            )
    document["suite_version"] = "0.1.18"
    with TARGET.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
