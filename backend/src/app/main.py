from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.analytics import router as analytics_router
from app.api.appointments import router as appointments_router
from app.api.auth import router as auth_router
from app.api.conversations import router as conversations_router
from app.api.dashboard import router as dashboard_router
from app.api.demo import router as demo_router
from app.api.health import router as health_router
from app.api.leads import router as leads_router
from app.api.organizations import router as organizations_router
from app.api.outbox import router as outbox_router
from app.api.services import router as services_router
from app.core.config import get_settings
from app.core.redis import redis_client

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan context for setup and graceful teardown."""
    yield
    # Cleanup Redis connection pool on shutdown
    await redis_client.aclose()


def create_application() -> FastAPI:
    """FastAPI application factory."""
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # CORS configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.FRONTEND_URL, "http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register Health Routes
    app.include_router(health_router)
    app.include_router(health_router, prefix=settings.API_V1_PREFIX)

    # Register API V1 Routers
    app.include_router(auth_router, prefix=settings.API_V1_PREFIX)
    app.include_router(organizations_router, prefix=settings.API_V1_PREFIX)
    app.include_router(leads_router, prefix=settings.API_V1_PREFIX)
    app.include_router(conversations_router, prefix=settings.API_V1_PREFIX)
    app.include_router(appointments_router, prefix=settings.API_V1_PREFIX)
    app.include_router(services_router, prefix=settings.API_V1_PREFIX)
    app.include_router(dashboard_router, prefix=settings.API_V1_PREFIX)
    app.include_router(analytics_router, prefix=settings.API_V1_PREFIX)
    app.include_router(outbox_router, prefix=settings.API_V1_PREFIX)
    app.include_router(demo_router, prefix=settings.API_V1_PREFIX)

    return app


app = create_application()
