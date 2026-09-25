"""Size-bounded, duplicate-key-safe loading for versioned golden suites."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from packages.evaluation.contracts import EvaluationSuite

MAX_SUITE_BYTES = 2 * 1024 * 1024


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_suite(path: Path) -> EvaluationSuite:
    if path.stat().st_size > MAX_SUITE_BYTES:
        raise ValueError("evaluation suite exceeds size limit")
    content = path.read_bytes()
    if len(content) > MAX_SUITE_BYTES:
        raise ValueError("evaluation suite exceeds size limit")
    decoded = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_keys)
    return EvaluationSuite.model_validate(decoded)
