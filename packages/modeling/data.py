"""Bounded preparation of complete training data; never fits preprocessing.

Only an internal current-authorizing loader may supply VerifiedTrainingSource.
Digest validation proves integrity, not permission. No API is exposed here.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from packages.modeling.contracts import MAX_MODEL_BYTES, MAX_ROWS, ModelSpec


class ModelDataError(ValueError):
    pass


@dataclass(frozen=True)
class VerifiedTrainingSource:
    artifact_id: uuid.UUID
    snapshot_id: uuid.UUID
    evidence_id: uuid.UUID
    data: dict[str, object]
    content_digest: str


@dataclass(frozen=True)
class PreparedTrainingData:
    spec: ModelSpec
    evidence_id: uuid.UUID
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    row_indices: tuple[int, ...]
    total_count: int
    dropped_count: int
    missing_counts: dict[str, int]
    feature_types: dict[str, Literal["numeric", "categorical"]]


def _numeric(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def prepare_training_data(
    spec: ModelSpec, loader: Callable[[uuid.UUID], VerifiedTrainingSource]
) -> PreparedTrainingData:
    """Reject truncation, record missing data, drop only missing target/split metadata.

    Feature imputation must happen after splitting in the future training pipeline.
    No silent sampling, DB connection, model construction or file write occurs.
    """
    spec = ModelSpec.model_validate(spec.model_dump())
    source = loader(spec.source_artifact_id)
    if (
        source.artifact_id != spec.source_artifact_id
        or source.snapshot_id != spec.source_snapshot_id
        or source.content_digest != spec.source_digest
    ):
        raise ModelDataError("model.source_mismatch")
    try:
        encoded = json.dumps(
            source.data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ModelDataError("model.invalid_table") from exc
    if len(encoded) > MAX_MODEL_BYTES:
        raise ModelDataError("model.data_limit")
    if hashlib.sha256(encoded).hexdigest() != source.content_digest:
        raise ModelDataError("model.digest_mismatch")
    columns, rows = source.data.get("columns"), source.data.get("rows")
    if (
        not isinstance(columns, list)
        or not columns
        or any(not isinstance(c, str) or not c.strip() for c in columns)
        or len(set(columns)) != len(columns)
        or not isinstance(rows, list)
        or any(not isinstance(r, list) or len(r) != len(columns) for r in rows)
    ):
        raise ModelDataError("model.invalid_table")
    if len(rows) > MAX_ROWS:
        raise ModelDataError("model.data_limit")
    count = source.data.get("row_count")
    if type(count) is not int or count != len(rows) or source.data.get("truncated") is not False:
        raise ModelDataError("model.incomplete_data")
    selected = (*spec.features, *(x for x in (spec.target, spec.time_field, spec.group_field) if x))
    if any(name not in columns for name in selected):
        raise ModelDataError("model.field_not_found")
    indices = [columns.index(name) for name in selected]
    projected = [tuple(row[i] for i in indices) for row in rows]
    # Query artifacts replace sensitive values with this exact sentinel. It is
    # not a missing value or a legitimate training category/target.
    if any(value == "***MASKED***" for row in projected for value in row):
        raise ModelDataError("model.masked_data")
    missing = {name: sum(row[i] is None for row in projected) for i, name in enumerate(selected)}
    types: dict[str, Literal["numeric", "categorical"]] = {}
    for i, name in enumerate(selected):
        values = [row[i] for row in projected if row[i] is not None]
        if not values:
            raise ModelDataError("model.empty_field")
        if any(
            not (_numeric(v) or isinstance(v, str) and 0 < len(v) <= 2000 and v.strip())
            for v in values
        ):
            raise ModelDataError("model.invalid_cell")
        numeric = all(_numeric(v) for v in values)
        if not numeric and not all(isinstance(v, str) for v in values):
            raise ModelDataError("model.mixed_feature_type")
        if name == spec.target and spec.task == "regression" and not numeric:
            raise ModelDataError("model.numeric_target_required")
        if name in spec.features:
            types[name] = "numeric" if numeric else "categorical"
    required_indices = range(len(spec.features), len(selected))
    retained = [
        i for i, row in enumerate(projected) if all(row[j] is not None for j in required_indices)
    ]
    minimum = 30 if spec.target else 20
    if len(retained) < minimum:
        raise ModelDataError("model.insufficient_samples")
    if spec.task == "classification":
        labels = Counter(projected[i][len(spec.features)] for i in retained)
        if any(isinstance(label, float) and not label.is_integer() for label in labels):
            raise ModelDataError("model.discrete_class_labels_required")
        if len(labels) < 2 or min(labels.values()) < 5:
            raise ModelDataError("model.insufficient_class_samples")
    if spec.task == "clustering" and len(retained) <= int(
        str(spec.effective_parameters()["n_clusters"])
    ):
        raise ModelDataError("model.clusters_require_more_samples")
    return PreparedTrainingData(
        spec,
        source.evidence_id,
        selected,
        tuple(projected[i] for i in retained),
        tuple(retained),
        len(rows),
        len(rows) - len(retained),
        missing,
        types,
    )
