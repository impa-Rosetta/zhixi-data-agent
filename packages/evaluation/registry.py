"""Server-owned suite registry; clients cannot submit paths or model instructions."""

from pathlib import Path

from packages.evaluation.contracts import EvaluationSuite
from packages.evaluation.suite_io import load_suite

SUITE_VERSIONS = ("0.1.5", "0.1.4", "0.1.3", "0.1.2")


def registered_suite(version: str) -> EvaluationSuite:
    if version not in SUITE_VERSIONS:
        raise ValueError("evaluation.suite_not_registered")
    root = Path(__file__).resolve().parents[2]
    return load_suite(root / f"evaluations/golden/manufacturing-quality-draft-v{version}.json")
