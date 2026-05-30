"""Neo4j 异步驱动连接（单例 + 连接池参数显式化）。"""
from neo4j import AsyncDriver, AsyncGraphDatabase

from app.config import settings

_driver: AsyncDriver | None = None


def get_driver() -> AsyncDriver:
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
            max_connection_pool_size=settings.neo4j_max_pool_size,
            connection_acquisition_timeout=settings.neo4j_connection_timeout,
        )
    return _driver


async def ping() -> bool:
    try:
        await get_driver().verify_connectivity()
        return True
    except Exception:
        return False


async def close() -> None:
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None
