"""Append an explicit API security attack matrix to the frozen draft."""

import json
from pathlib import Path

from packages.evaluation import load_suite
from packages.evaluation.security_draft_adapter import SQL_ATTACKS

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.8.json"


def main() -> None:
    previous = load_suite(ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.7.json")
    if previous.published or len(previous.cases) != 37:
        raise ValueError("Frozen baseline changed")
    document = previous.model_dump(mode="json")
    for key, (question, _sql, code) in SQL_ATTACKS.items():
        document["cases"].append(
            {
                "id": f"security-sql-{key}",
                "category": "security",
                "probe_kind": "system_gate",
                "turns": [question],
                "rationale": "实际调用受权探索查询API，验证特定攻击被稳定错误码阻断，执行器不触达且无副作用。",  # noqa: E501
                "expected": {
                    "status": "denied",
                    "allowed_tools": [],
                    "numbers": {},
                    "require_evidence": False,
                    "safety_kind": "dangerous_sql",
                    "safety_entrypoint": "api.validate_exploratory",
                    "safety_gate_codes": [code],
                },
            }
        )
    document["suite_version"] = "0.1.8"
    with TARGET.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
