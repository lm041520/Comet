"""Redis 异步客户端（显式连接池 + 健康检查）。"""
from redis import asyncio as aioredis

from app.config import settings

_pool: aioredis.ConnectionPool | None = None
_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _pool, _client
    if _client is None:
        _pool = aioredis.ConnectionPool.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=settings.redis_max_connections,
            health_check_interval=30,
        )
        _client = aioredis.Redis(connection_pool=_pool)
    return _client


async def ping() -> bool:
    try:
        return await get_redis().ping()
    except Exception:
        return False


async def close() -> None:
    global _pool, _client
    if _client is not None:
        await _client.aclose()
        _client = None
    if _pool is not None:
        await _pool.disconnect()
        _pool = None
