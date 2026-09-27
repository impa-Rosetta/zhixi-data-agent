"""Append provider HTTP and transport failure cases to the immutable golden draft."""

import json
from pathlib import Path

from packages.evaluation import load_suite

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.9.json"


def main() -> None:
    previous = load_suite(ROOT / "evaluations/golden/manufacturing-quality-draft-v0.1.8.json")
    if previous.published or len(previous.cases) != 55:
        raise ValueError("Frozen baseline changed")
    document = previous.model_dump(mode="json")
    for key, reason in (
        ("timeout", "读取超时"),
        ("connection", "连接失败"),
        ("rate-limit", "HTTP429限流"),
        ("unavailable", "HTTP503服务不可用"),
        ("authentication", "HTTP401鉴权失败"),
        ("rejected", "HTTP400请求拒绝"),
        ("invalid-response", "HTTP200返回无效协议响应"),
    ):
        document["cases"].append(
            {
                "id": f"anomaly-provider-{key}",
                "category": "anomaly",
                "turns": ["分析不良率"],
                "rationale": f"合成传输模拟{reason}，实际网关重试和Agent安全失败，供应商正文与凭据不入回答。",  # noqa: E501
                "expected": {
                    "status": "failed",
                    "allowed_tools": [],
                    "numbers": {},
                    "require_evidence": False,
                },
            }
        )
    document["suite_version"] = "0.1.9"
    with TARGET.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
