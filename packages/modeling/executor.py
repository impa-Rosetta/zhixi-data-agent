"""Fixed file protocol for the non-networked modeling container only.

Host agent must authorize the persisted job and its source before mounting files.
This process has no DB/object-store credentials and cannot grant authorization.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from packages.modeling.contracts import (
    MAX_MODEL_BYTES,
    Digest,
    ModelSpec,
    ModelTrainingResult,
    PredictionRequest,
)
from packages.modeling.data import ModelDataError, VerifiedTrainingSource
from packages.modeling.inference import predict_internal_model
from packages.modeling.snapshots import decode_training_snapshot
from packages.modeling.training import train_model


class ExecutorJob(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    version: Literal[1] = 1
    job_id: uuid.UUID
    attempt_id: uuid.UUID
    operation: Literal["train", "predict"]
    input_digest: Digest
    spec: ModelSpec | None = None
    model_result: ModelTrainingResult | None = None
    prediction: PredictionRequest | None = None
    model_version_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def operation_fields(self) -> Self:
        if self.operation == "train":
            if self.spec is None or any(
                value is not None
                for value in (self.model_result, self.prediction, self.model_version_id)
            ):
                raise ValueError("model.invalid_train_job")
        elif (
            self.spec is not None
            or self.model_result is None
            or self.prediction is None
            or self.model_version_id is None
            or self.prediction.model_version_id != self.model_version_id
            or self.model_result.model_file.content_digest != self.input_digest
        ):
            raise ValueError("model.invalid_predict_job")
        return self


class _FrozenSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    version: Literal[1]
    spec: ModelSpec
    evidence_id: uuid.UUID
    data: dict[str, object]


def _read(path: Path, limit: int = MAX_MODEL_BYTES) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ModelDataError("model.invalid_input_file")
    with path.open("rb") as handle:
        content = handle.read(limit + 1)
    if len(content) > limit:
        raise ModelDataError("model.input_too_large")
    return content


def execute_job(job: ExecutorJob, content: bytes) -> tuple[dict[str, object], bytes | None]:
    """Only fixed algorithms execute; no user scripts/imports/paths are accepted."""
    job = ExecutorJob.model_validate(job.model_dump())
    if len(content) > MAX_MODEL_BYTES or hashlib.sha256(content).hexdigest() != job.input_digest:
        raise ModelDataError("model.input_integrity_mismatch")
    model_content: bytes | None = None
    if job.operation == "train":
        assert job.spec is not None
        frozen = _FrozenSnapshot.model_validate_json(content)
        source = VerifiedTrainingSource(
            job.spec.source_artifact_id,
            job.spec.source_snapshot_id,
            frozen.evidence_id,
            frozen.data,
            job.spec.source_digest,
        )
        # Authority was checked by the host, not by this isolated frozen loader.
        data = decode_training_snapshot(content, job.input_digest, job.spec, lambda _: source)
        output = train_model(data)
        payload: dict[str, object] = {
            "training_result": output.result.model_dump(mode="json"),
            "explanation": output.explanation,
            "train_indices": list(output.train_indices),
            "validation_indices": list(output.validation_indices),
            "validation_predictions": list(output.validation_predictions),
            "source_row_indices": list(data.row_indices),
        }
        model_content = output.model_bytes
    else:
        assert job.model_result is not None and job.prediction is not None
        assert job.model_version_id is not None
        payload = predict_internal_model(
            content,
            job.model_result,
            job.prediction,
            authorized_version_id=job.model_version_id,
        )
    envelope: dict[str, object] = {
        "version": 1,
        "job_id": str(job.job_id),
        "attempt_id": str(job.attempt_id),
        "operation": job.operation,
        "payload": payload,
    }
    encoded = json.dumps(envelope, allow_nan=False, separators=(",", ":")).encode()
    if len(encoded) + len(model_content or b"") > MAX_MODEL_BYTES:
        raise ModelDataError("model.output_too_large")
    return envelope, model_content


def main() -> int:
    """Fixed mounts only. Never emits tracebacks or input contents to stdout."""
    if os.environ.get("ZHIXI_MODEL_EXECUTOR") != "isolated-v1":
        raise ModelDataError("model.executor_not_configured")
    output_dir = Path("/output")
    try:
        job = ExecutorJob.model_validate_json(_read(Path("/input/job.json"), 2 * 1024 * 1024))
        content = _read(
            Path("/input/snapshot.json" if job.operation == "train" else "/input/model.skops")
        )
        envelope, model_content = execute_job(job, content)
        # Fresh per-attempt output mount; exclusive writes avoid replacement/symlink attacks.
        if model_content is not None:
            with (output_dir / "model.skops").open("xb") as handle:
                handle.write(model_content)
        with (output_dir / "result.json").open("xb") as handle:
            handle.write(json.dumps(envelope, allow_nan=False, separators=(",", ":")).encode())
        return 0
    except Exception:
        # Detailed safe state is recorded by host; this container logs no sensitive values.
        print("model.executor_failed", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
