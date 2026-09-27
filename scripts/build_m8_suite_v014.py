"""Create the immutable 0.1.4 draft with a catalog/source drift case."""

from __future__ import annotations

import json
from pathlib import Path

from packages.evaluation import load_suite

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.3.json"
TARGET = ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.4.json"


def build_suite() -> dict[str, object]:
    old = load_suite(SOURCE)
    if old.suite_version != "0.1.3" or old.published or len(old.cases) != 15:
        raise ValueError("Frozen baseline changed; re-review source first")
    document = old.model_dump(mode="json")
    cases = document["cases"]
    assert isinstance(cases, list)
    cases.append(
        {
            "id": "anomaly-source-column-disappeared",
            "category": "anomaly",
            "turns": ["2026年9月的不良率是多少？"],
            "rationale": (
                "仅在本案例独立临时 schema 内发布语义映射后删除 defect_quantity 字段，"
                "真实只读查询必须失败；回答不得编造数字、结果或证据。"
            ),
            "expected": {
                "status": "failed",
                "allowed_tools": ["semantic.resolve", "query.metric"],
                "numbers": {},
                "require_evidence": False,
            },
        }
    )
    document["suite_version"] = "0.1.4"
    document["published"] = False
    return document


def main() -> None:
    document = build_suite()
    with TARGET.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
