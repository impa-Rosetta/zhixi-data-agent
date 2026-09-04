from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel

from packages.platform_core.settings import get_settings

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    timestamp: datetime


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service="api",
        version=settings.app_version,
        timestamp=datetime.now(UTC),
    )
