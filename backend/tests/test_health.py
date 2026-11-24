import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_liveness(async_client: AsyncClient) -> None:
    """Verify that the GET /health liveness endpoint returns 200 OK."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_ready(async_client: AsyncClient) -> None:
    """Verify that the GET /health/ready endpoint can connect to PostgreSQL and Redis."""
    response = await async_client.get("/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["services"]["database"] == "connected"
    assert data["services"]["redis"] == "connected"


@pytest.mark.asyncio
async def test_api_prefix_health(async_client: AsyncClient) -> None:
    """Verify that /api/health also responds under the configured API prefix."""
    response = await async_client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
