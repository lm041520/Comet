"""PostgreSQL 异步连接（SQLAlchemy 2.0）。

连接池参数显式化：pool_pre_ping 剔除失效连接，
pool_recycle 防被 DB 端断开，statement_timeout 防慢查询挂死。
"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    future=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
    pool_pre_ping=settings.db_pool_pre_ping,
    # asyncpg 用 server_settings 设单条 SQL 超时（毫秒）
    connect_args={
        "server_settings": {
            "timezone": "UTC",
            "statement_timeout": str(settings.db_statement_timeout_ms),
        }
    },
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def ping() -> bool:
    from sqlalchemy import text

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def get_pool_status() -> dict:
    """连接池状态（监控用）。"""
    pool = engine.pool
    return {
        "size": pool.size(),
        "checked_in": pool.checkedin(),
        "checked_out": pool.checkedout(),
        "overflow": pool.overflow(),
    }


async def close() -> None:
    await engine.dispose()
