"""Host-only polling entry point for persisted model training jobs.

Deploy this as a separate trusted process on a machine with Docker CLI access.
Neither API nor ordinary Worker imports or runs it.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from apps.host.modeling_runtime import (
    ContainerRunner,
    DockerCLIModelRunner,
    SessionFactory,
    run_training_job,
)
from packages.modeling.data import ModelDataError
from packages.modeling.job_store import (
    MAX_ATTEMPTS,
    reap_exhausted_training,
    reject_queued_training,
)
from packages.modeling.object_storage import MinioModelObjectStorage
from packages.modeling.persistence import ModelJob
from packages.modeling.snapshot_storage import SnapshotObjectStorage
from packages.platform_core.database import get_engine
from packages.platform_core.settings import get_settings

logger = logging.getLogger(__name__)


def poll_once(
    *,
    db_factory: SessionFactory,
    storage: SnapshotObjectStorage,
    image_id: str,
    runner: ContainerRunner,
    batch_size: int = 20,
) -> int:
    """Find a bounded batch, reap exhausted leases, then execute claimable IDs.

    Concurrent host agents may see the same ID; claim_training owns the atomic
    state transition, so only one attempt proceeds. No user flags are accepted.
    """
    if not 1 <= batch_size <= 100:
        raise ValueError("invalid batch size")
    now = datetime.now(UTC)
    with db_factory() as db:
        expired = and_(ModelJob.status == "running", ModelJob.lease_expires_at < now)
        jobs = db.execute(
            select(ModelJob.id, ModelJob.workspace_id, ModelJob.attempt_count)
            .where(ModelJob.operation == "train", or_(ModelJob.status == "queued", expired))
            .order_by(ModelJob.created_at, ModelJob.id)
            .limit(batch_size)
        ).all()
        for job_id, workspace_id, attempts in jobs:
            if attempts >= MAX_ATTEMPTS:
                reap_exhausted_training(db, workspace_id=workspace_id, job_id=job_id, now=now)
        db.commit()
    dispatched = 0
    for job_id, workspace_id, attempts in jobs:
        if attempts >= MAX_ATTEMPTS:
            continue
        try:
            run_training_job(
                uuid.UUID(str(job_id)),
                db_factory=db_factory,
                storage=storage,
                image_id=image_id,
                runner=runner,
            )
        except Exception as exc:
            # Concurrent claim, source revocation and transient DB failure leave
            # the job unexecuted. Deterministic revocation is terminal; only
            # transient failures may be retried by a later poll.
            code = str(exc) if isinstance(exc, ModelDataError) else "model.host_unavailable"
            if code in {"policy.denied", "model.source_mismatch"}:
                with db_factory() as db:
                    reject_queued_training(
                        db, workspace_id=workspace_id, job_id=job_id, error_code=code
                    )
                    db.commit()
            logger.warning("model job not dispatched: job_id=%s code=%s", job_id, code)
            continue
        dispatched += 1
    return dispatched


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Trusted host-only model training agent")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.interval <= 60:
        parser.error("interval must be 1-60 seconds")
    image_id = os.environ.get("ZHIXI_MODEL_IMAGE_ID", "")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
        parser.error("ZHIXI_MODEL_IMAGE_ID must be an exact local SHA256 image ID")
    settings = get_settings()
    storage = MinioModelObjectStorage(
        endpoint_url=settings.s3_endpoint_url,
        access_key=settings.s3_access_key.get_secret_value(),
        secret_key=settings.s3_secret_key.get_secret_value(),
        bucket=settings.s3_bucket,
    )

    def db_factory() -> Session:
        return Session(get_engine())

    runner = DockerCLIModelRunner()
    while True:
        poll_once(db_factory=db_factory, storage=storage, image_id=image_id, runner=runner)
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
