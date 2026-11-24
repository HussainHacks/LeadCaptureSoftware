import redis.asyncio as aioredis

from app.core.config import get_settings

settings = get_settings()

redis_client = aioredis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    socket_timeout=3.0,
    socket_connect_timeout=3.0,
)


async def check_redis_connection() -> bool:
    """Verify connectivity to Redis by issuing a PING."""
    try:
        return await redis_client.ping() is True
    except Exception:
        return False
