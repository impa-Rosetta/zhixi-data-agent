from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routes.analysis_conversations import router as analysis_conversations_router
from apps.api.routes.analysis_reports import router as analysis_reports_router
from apps.api.routes.analysis_runs import router as analysis_runs_router
from apps.api.routes.auth import router as auth_router
from apps.api.routes.data_sources import router as data_sources_router
from apps.api.routes.health import router as health_router
from apps.api.routes.queries import router as queries_router
from apps.api.routes.semantic_models import router as semantic_models_router
from apps.api.routes.workspaces import router as workspaces_router
from packages.platform_core.settings import get_settings


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    get_settings()
    yield


settings = get_settings()
app = FastAPI(
    title="智析 Data Agent API",
    version=settings.app_version,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Idempotency-Key",
        "Last-Event-ID",
        "X-Request-ID",
    ],
)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(workspaces_router)
app.include_router(data_sources_router)
app.include_router(semantic_models_router)
app.include_router(queries_router)
app.include_router(analysis_conversations_router)
app.include_router(analysis_runs_router)
app.include_router(analysis_reports_router)
