from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.analytics import router as analytics_router
from app.api.appointments import router as appointments_router
from app.api.auth import router as auth_router
from app.api.conversations import router as conversations_router
from app.api.dashboard import router as dashboard_router
from app.api.health import router as health_router
from app.api.leads import router as leads_router
from app.api.organizations import router as organizations_router
from app.api.outbox import router as outbox_router
from app.api.public import router as public_router
from app.api.services import router as services_router
from app.core.config import Settings, get_settings
from app.core.redis import redis_client

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan context for setup and graceful teardown."""
    yield
    # Cleanup Redis connection pool on shutdown
    await redis_client.aclose()


def create_application(app_settings: Settings | None = None) -> FastAPI:
    """FastAPI application factory."""
    cfg = app_settings or settings

    if cfg.DEMO_ENABLED and (not cfg.DEMO_PASSWORD or not cfg.DEMO_PASSWORD.strip()):
        raise RuntimeError("DEMO_PASSWORD must be set when DEMO_ENABLED is true.")

    app = FastAPI(
        title=cfg.PROJECT_NAME,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # CORS configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[cfg.FRONTEND_URL, "http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register Health Routes
    app.include_router(health_router)
    app.include_router(health_router, prefix=cfg.API_V1_PREFIX)

    # Register API V1 Routers
    app.include_router(auth_router, prefix=cfg.API_V1_PREFIX)
    app.include_router(organizations_router, prefix=cfg.API_V1_PREFIX)
    app.include_router(leads_router, prefix=cfg.API_V1_PREFIX)
    app.include_router(conversations_router, prefix=cfg.API_V1_PREFIX)
    app.include_router(appointments_router, prefix=cfg.API_V1_PREFIX)
    app.include_router(services_router, prefix=cfg.API_V1_PREFIX)
    app.include_router(dashboard_router, prefix=cfg.API_V1_PREFIX)
    app.include_router(analytics_router, prefix=cfg.API_V1_PREFIX)
    app.include_router(outbox_router, prefix=cfg.API_V1_PREFIX)
    app.include_router(public_router, prefix=cfg.API_V1_PREFIX)

    if cfg.DEMO_ENABLED:
        from app.api.demo import router as demo_router

        app.include_router(demo_router, prefix=cfg.API_V1_PREFIX)

    return app


app = create_application()
