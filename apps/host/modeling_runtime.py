"""Run a persisted training attempt in the fixed modeling container.

This module is only for the trusted host process. API/Worker receive no Docker
socket. A failed/absent host agent leaves jobs queued; there is no direct-train
fallback. The host receives only a persisted job UUID, not runtime flags.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.services.modeling_sources import load_training_source
from packages.modeling.contracts import MAX_MODEL_BYTES, ModelSpec, ModelTrainingResult
from packages.modeling.data import ModelDataError, VerifiedTrainingSource
from packages.modeling.host_policy import fixed_training_container_command
from packages.modeling.job_store import claim_training, fail_attempt, publish_training_version
from packages.modeling.persistence import ModelJob, TrainingSnapshotRecord
from packages.modeling.snapshot_storage import (
    SnapshotObjectStorage,
    SnapshotReceipt,
    read_training_snapshot,
)

SessionFactory = Callable[[], Session]


class ContainerRunner(Protocol):
    def run(self, args: tuple[str, ...], *, cancelled: Callable[[], bool]) -> None: ...


class DockerCLIModelRunner:
    """Only for a locally managed host process with Docker CLI access."""

    def run(self, args: tuple[str, ...], *, cancelled: Callable[[], bool]) -> None:
        name = args[args.index("--name") + 1]
        created = False
        try:
            subprocess.run(args, check=True, capture_output=True, timeout=30)
            created = True
            process = subprocess.Popen(
                ["docker", "start", "--attach", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            deadline = time.monotonic() + 300
            try:
                while process.poll() is None:
                    if cancelled():
                        raise ModelDataError("model.job_cancelled_or_revoked")
                    if time.monotonic() >= deadline:
                        raise ModelDataError("model.execution_timeout")
                    time.sleep(1)
                if process.returncode != 0:
                    raise ModelDataError("model.executor_failed")
            finally:
                if process.poll() is None:
                    with suppress(OSError, subprocess.SubprocessError):
                        subprocess.run(
                            ["docker", "rm", "--force", name],
                            capture_output=True,
                            timeout=30,
                        )
                    with suppress(OSError, subprocess.SubprocessError):
                        process.wait(timeout=10)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ModelDataError("model.executor_unavailable") from exc
        finally:
            if created:
                with suppress(OSError, subprocess.SubprocessError):
                    subprocess.run(
                        ["docker", "rm", "--force", name], capture_output=True, timeout=30
                    )


def run_training_job(
    job_id: uuid.UUID,
    *,
    db_factory: SessionFactory,
    storage: SnapshotObjectStorage,
    image_id: str,
    runner: ContainerRunner,
) -> uuid.UUID | None:
    """Claim, reauthorize, run, validate and publish one persisted task ID.

    Returns a model version ID only after the database transaction commits.
    The caller's process must already have authorized Docker CLI access.
    """
    with db_factory() as db:
        job = db.get(ModelJob, job_id)
        if job is None or job.operation != "train":
            raise ModelDataError("model.job_not_found")
        workspace_id, actor_id = job.workspace_id, job.created_by_user_id
        spec = ModelSpec.model_validate(job.spec)

        def loader(artifact_id: uuid.UUID) -> VerifiedTrainingSource:
            return load_training_source(
                db,
                workspace_id=workspace_id,
                actor_user_id=actor_id,
                artifact_id=artifact_id,
                snapshot_id=spec.source_snapshot_id,
                content_digest=spec.source_digest,
            )

        claimed = claim_training(db, workspace_id=workspace_id, job_id=job_id, loader=loader)
        attempt_id = claimed.attempt_id
        assert attempt_id is not None
        training_snapshot_id = claimed.training_snapshot_id
        db.commit()

    try:
        with db_factory() as db:
            snapshot = db.scalar(
                select(TrainingSnapshotRecord).where(
                    TrainingSnapshotRecord.workspace_id == workspace_id,
                    TrainingSnapshotRecord.id == training_snapshot_id,
                )
            )
            if snapshot is None:
                raise ModelDataError("model.snapshot_not_found")
            receipt = SnapshotReceipt(
                workspace_id=workspace_id,
                snapshot_id=snapshot.id,
                digest=snapshot.content_digest,
                size_bytes=snapshot.size_bytes,
            )

            def snapshot_loader(artifact_id: uuid.UUID) -> VerifiedTrainingSource:
                return load_training_source(
                    db,
                    workspace_id=workspace_id,
                    actor_user_id=actor_id,
                    artifact_id=artifact_id,
                    snapshot_id=spec.source_snapshot_id,
                    content_digest=spec.source_digest,
                )

            prepared = read_training_snapshot(storage, workspace_id, receipt, spec, snapshot_loader)
            content = storage.get(receipt.object_key, max_bytes=MAX_MODEL_BYTES)
            if (
                len(content) != receipt.size_bytes
                or hashlib.sha256(content).hexdigest() != receipt.digest
            ):
                raise ModelDataError("model.snapshot_digest_mismatch")
        with tempfile.TemporaryDirectory(prefix="zhixi-model-") as directory:
            root = Path(directory)
            inputs, outputs = root / "input", root / "output"
            inputs.mkdir()
            outputs.mkdir()
            from packages.modeling.executor import ExecutorJob

            envelope = ExecutorJob(
                job_id=job_id,
                attempt_id=attempt_id,
                operation="train",
                input_digest=receipt.digest,
                spec=spec,
            )
            (inputs / "job.json").write_text(envelope.model_dump_json(), encoding="utf-8")
            (inputs / "snapshot.json").write_bytes(content)
            name = "zhixi-model-" + uuid.uuid4().hex
            args = fixed_training_container_command(
                image_id=image_id, container_name=name, attempt_root=root
            )

            def cancelled() -> bool:
                try:
                    with db_factory() as check_db:
                        current = check_db.get(ModelJob, job_id)
                        if (
                            current is None
                            or current.workspace_id != workspace_id
                            or current.status != "running"
                            or current.attempt_id != attempt_id
                        ):
                            return True
                        load_training_source(
                            check_db,
                            workspace_id=workspace_id,
                            actor_user_id=actor_id,
                            artifact_id=spec.source_artifact_id,
                            snapshot_id=spec.source_snapshot_id,
                            content_digest=spec.source_digest,
                        )
                        return False
                except Exception:
                    # A host that cannot prove continued authorization stops execution.
                    return True

            runner.run(args, cancelled=cancelled)
            files = list(outputs.iterdir())
            if {path.name for path in files} != {"result.json", "model.skops"} or any(
                path.is_symlink() or not path.is_file() for path in files
            ):
                raise ModelDataError("model.invalid_executor_output")
            if sum(path.stat().st_size for path in files) > MAX_MODEL_BYTES:
                raise ModelDataError("model.output_too_large")
            raw = (outputs / "result.json").read_bytes()
            model_content = (outputs / "model.skops").read_bytes()
            output = json.loads(raw)
            if (
                set(output) != {"version", "job_id", "attempt_id", "operation", "payload"}
                or output["version"] != 1
                or output["job_id"] != str(job_id)
                or output["attempt_id"] != str(attempt_id)
                or output["operation"] != "train"
                or not isinstance(output["payload"], dict)
            ):
                raise ModelDataError("model.invalid_executor_output")
            result = ModelTrainingResult.model_validate(output["payload"]["training_result"])
            if result.spec != spec:
                raise ModelDataError("model.executor_spec_mismatch")
            with db_factory() as db:

                def publication_loader(artifact_id: uuid.UUID) -> VerifiedTrainingSource:
                    return load_training_source(
                        db,
                        workspace_id=workspace_id,
                        actor_user_id=actor_id,
                        artifact_id=artifact_id,
                        snapshot_id=spec.source_snapshot_id,
                        content_digest=spec.source_digest,
                    )

                version = publish_training_version(
                    db,
                    workspace_id=workspace_id,
                    job_id=job_id,
                    attempt_id=attempt_id,
                    model_name=f"{spec.algorithm}-{str(job_id)[:8]}",
                    result=result,
                    model_content=model_content,
                    storage=storage,
                    feature_types=dict(prepared.feature_types),
                    loader=publication_loader,
                )
                db.commit()
                return version.id
    except Exception as exc:
        with db_factory() as db:
            fail_attempt(
                db,
                workspace_id=workspace_id,
                job_id=job_id,
                attempt_id=attempt_id,
                error_code=(
                    str(exc)
                    if isinstance(exc, ModelDataError) and len(str(exc)) <= 100
                    else "model.executor_failed"
                ),
            )
            db.commit()
        return None
