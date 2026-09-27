"""Run reviewed cases against the dedicated synthetic Docker PostgreSQL fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from packages.evaluation import load_suite, run_offline_suite
from packages.evaluation.postgres_draft_adapter import ADAPTER_VERSION, postgres_case_factory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite-version",
        choices=(
            "0.1.0",
            "0.1.1",
            "0.1.2",
            "0.1.3",
            "0.1.4",
            "0.1.5",
            "0.1.6",
            "0.1.7",
            "0.1.8",
            "0.1.9",
            "0.1.10",
            "0.1.11",
            "0.1.12",
        ),
        default="0.1.12",
    )
    parser.add_argument("--output", type=Path, help="New report path, never overwritten")
    args = parser.parse_args()
    if args.output is not None and args.output.exists():
        raise FileExistsError(args.output)
    root = Path(__file__).resolve().parents[1]
    suite = load_suite(
        root / f"evaluations/golden/manufacturing-quality-draft-v{args.suite_version}.json"
    )
    result = run_offline_suite(suite, postgres_case_factory)
    payload = json.loads(result.to_json())
    payload.update(
        adapter_version=ADAPTER_VERSION,
        suite_published=suite.published,
        runtime_profile="isolated-postgresql-and-sqlite-api-fixed-gateway-real-query-executor",
    )
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    if args.output is not None:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(content + "\n")
    print(content)
    return 0 if result.summary.passed == result.summary.total else 1


if __name__ == "__main__":
    raise SystemExit(main())
