from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.core.database import check_database_connection
from app.core.redis import check_redis_connection

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("", status_code=status.HTTP_200_OK)
async def liveness_check() -> dict[str, str]:
    """Basic liveness check indicating the process is running."""
    return {"status": "ok"}


@router.get("/ready")
async def readiness_check() -> JSONResponse:
    """Readiness probe verifying PostgreSQL and Redis connections without leaking credentials."""
    db_healthy = await check_database_connection()
    redis_healthy = await check_redis_connection()

    all_ready = db_healthy and redis_healthy

    payload = {
        "status": "ready" if all_ready else "degraded",
        "services": {
            "database": "connected" if db_healthy else "disconnected",
            "redis": "connected" if redis_healthy else "disconnected",
        },
    }

    status_code = status.HTTP_200_OK if all_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=status_code, content=payload)
