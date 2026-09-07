import uuid

from sqlalchemy.orm import Session

from apps.worker.analysis_runtime import run_analysis
from apps.worker.celery_app import celery_app
from packages.model_gateway import DeepSeekGateway
from packages.platform_core.database import get_engine
from packages.platform_core.settings import get_settings


@celery_app.task(
    name="analysis_runs.execute",
    acks_late=True,
)  # type: ignore[untyped-decorator]
def execute_analysis_run(run_id: str) -> None:
    settings = get_settings()
    gateway = DeepSeekGateway(
        api_key=settings.deepseek_api_key.get_secret_value(),
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        timeout_seconds=settings.deepseek_timeout_seconds,
        max_attempts=settings.deepseek_max_attempts,
    )
    with Session(get_engine()) as db:
        run_analysis(db, run_id=uuid.UUID(run_id), gateway=gateway)
