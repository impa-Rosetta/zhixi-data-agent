"""Freeze four distinct missing-information routes without rewriting prior cases."""

import json
from pathlib import Path

from packages.evaluation import load_suite

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.13.json"


def main() -> None:
    previous = load_suite(ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.12.json")
    if previous.published or len(previous.cases) != 76:
        raise ValueError("Frozen baseline changed")
    document = previous.model_dump(mode="json")
    for key, question, rationale in (
        ("trend-metric", "看看最近三个月的趋势", "趋势路由缺少指标，不应查询或猜测指标"),
        ("ranking-metric", "哪些工单排名最高？", "排名路由缺少指标，不应猜测排名依据"),
        ("comparison-current-period", "不良率与上月对比", "已给对比周期，仅请求缺失的当前周期"),
        ("comparison-baseline-period", "比较本月不良率", "已给当前周期，仅请求缺失的对比周期"),
    ):
        document["cases"].append(
            {
                "id": f"ambiguity-{key}",
                "category": "ambiguity",
                "turns": [question],
                "rationale": rationale
                + "；真实持久化澄清必须以自然语言展示，且无工具或证据副作用。",
                "expected": {
                    "status": "clarification",
                    "allowed_tools": [],
                    "require_evidence": False,
                },
            }
        )
    document["suite_version"] = "0.1.13"
    with TARGET.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
