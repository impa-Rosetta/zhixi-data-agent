import uuid
from typing import Any

from sqlalchemy.orm import Session

from apps.worker.celery_app import celery_app
from packages.platform_core.data_source_jobs import RetryableConnectionTest, run_connection_test
from packages.platform_core.database import get_engine
from packages.platform_core.settings import get_settings


@celery_app.task(
    bind=True,
    name="data_sources.test_connection",
    max_retries=2,
    acks_late=True,
)  # type: ignore[untyped-decorator]
def test_connection(self: Any, job_id: str) -> None:
    try:
        with Session(get_engine()) as db:
            run_connection_test(db, job_id=uuid.UUID(job_id), settings=get_settings())
    except RetryableConnectionTest as exc:
        retry = self.retry
        request = self.request
        retries = int(getattr(request, "retries", 0))
        raise retry(exc=exc, countdown=2 ** (retries + 1)) from exc
