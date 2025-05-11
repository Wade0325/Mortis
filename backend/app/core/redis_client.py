# backend/app/core/redis_client.py
import redis.asyncio as aioredis # For FastAPI SSE
import redis # For Celery tasks (sync client often simpler there)
from .config import settings
# Async client for FastAPI (e.g., for SSE pub/sub)
async_redis_pool = aioredis.from_url(settings.REDIS_PUB_SUB_URL, decode_responses=True)
# Sync client for Celery tasks or synchronous parts of services
sync_redis_client = redis.Redis.from_url(settings.REDIS_PUB_SUB_URL, decode_responses=True)
async def get_async_redis_client():
    """Dependency for FastAPI to get an async Redis client."""
    return async_redis_pool
def get_sync_redis_client():
    """Utility to get a sync Redis client."""
    return sync_redis_client