"""Run the reviewed first draft without network, credentials or fake metric values."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from packages.evaluation import load_suite, run_offline_suite
from packages.evaluation.draft_adapter import ADAPTER_VERSION, draft_case_factory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, help="New report file; existing files are never overwritten"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    suite = load_suite(root / "evaluations/golden/manufacturing-quality-draft-v0.1.0.json")
    result = run_offline_suite(suite, draft_case_factory)
    payload = json.loads(result.to_json())
    payload["adapter_version"] = ADAPTER_VERSION
    payload["suite_published"] = suite.published
    payload["runtime_profile"] = "isolated-sqlite-fixed-fakegateway-no-metric-executor"
    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(content + "\n")
    print(content)
    # Partial coverage must not turn CI green; zero requires all cases passed.
    return 0 if result.summary.passed == result.summary.total else 1


if __name__ == "__main__":
    raise SystemExit(main())
