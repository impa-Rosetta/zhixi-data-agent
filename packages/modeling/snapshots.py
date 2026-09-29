"""Immutable bounded training bytes; stored snapshots never confer authority."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from packages.modeling.contracts import MAX_MODEL_BYTES, ModelSpec
from packages.modeling.data import (
    ModelDataError,
    PreparedTrainingData,
    VerifiedTrainingSource,
    prepare_training_data,
)

SourceLoader = Callable[[uuid.UUID], VerifiedTrainingSource]


class _Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    version: Literal[1]
    spec: ModelSpec
    evidence_id: uuid.UUID
    data: dict[str, object]


@dataclass(frozen=True)
class TrainingSnapshotBytes:
    content: bytes
    digest: str
    total_count: int
    sample_count: int
    dropped_count: int


def encode_training_snapshot(spec: ModelSpec, loader: SourceLoader) -> TrainingSnapshotBytes:
    source = loader(spec.source_artifact_id)
    prepared = prepare_training_data(spec, lambda _: source)
    # Freeze a full copy, never a mutable pointer or a page of the result.
    snapshot = _Snapshot(
        version=1, spec=prepared.spec, evidence_id=source.evidence_id, data=source.data
    )
    content = json.dumps(
        snapshot.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(content) > MAX_MODEL_BYTES:
        raise ModelDataError("model.data_limit")
    return TrainingSnapshotBytes(
        content,
        hashlib.sha256(content).hexdigest(),
        prepared.total_count,
        len(prepared.rows),
        prepared.dropped_count,
    )


def decode_training_snapshot(
    content: bytes, expected_digest: str, spec: ModelSpec, loader: SourceLoader
) -> PreparedTrainingData:
    if len(content) > MAX_MODEL_BYTES:
        raise ModelDataError("model.data_limit")
    if hashlib.sha256(content).hexdigest() != expected_digest:
        raise ModelDataError("model.snapshot_digest_mismatch")
    try:
        snapshot = _Snapshot.model_validate_json(content)
    except (ValidationError, ValueError) as exc:
        raise ModelDataError("model.invalid_snapshot") from exc
    if snapshot.spec != ModelSpec.model_validate(spec.model_dump()):
        raise ModelDataError("model.snapshot_spec_mismatch")
    current = loader(spec.source_artifact_id)
    # Current authorization and full source validation must precede reuse.
    prepare_training_data(spec, lambda _: current)
    if current.evidence_id != snapshot.evidence_id:
        raise ModelDataError("model.source_mismatch")
    frozen = VerifiedTrainingSource(
        spec.source_artifact_id,
        spec.source_snapshot_id,
        snapshot.evidence_id,
        snapshot.data,
        spec.source_digest,
    )
    return prepare_training_data(spec, lambda _: frozen)
