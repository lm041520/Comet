"""定时任务（Celery beat）：每日回顾批量生成。

每天定时为所有用户生成当日回顾简报，写入 daily_reviews。
与文档/记忆任务一致：任务级独立引擎 + 独立事件循环。
"""
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.models  # noqa: F401  确保 ORM 模型注册
from app.celery_app import celery_app
from app.core.logging import get_logger
from app.db.postgres import create_task_engine
from app.models.user_model import User
from app.services.daily_review_service import DailyReviewService

logger = get_logger(__name__)


async def _run() -> int:
    engine = create_task_engine()
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )
    count = 0
    try:
        async with session_maker() as session:
            result = await session.execute(select(User.id))
            user_ids = [row[0] for row in result.all()]
            service = DailyReviewService(session)
            for uid in user_ids:
                try:
                    await service.get_or_generate(uid)
                    count += 1
                except Exception as e:
                    logger.warning("用户 %s 每日回顾生成失败: %s", uid, e)
    finally:
        await engine.dispose()
    logger.info("每日回顾批量生成完成: %d 个用户", count)
    return count


@celery_app.task(name="app.tasks.beat.generate_daily_reviews")
def generate_daily_reviews_task() -> int:
    """每日回顾批量生成的 Celery 任务入口。"""
    return asyncio.run(_run())


async def _run_clustering() -> int:
    """为所有用户跑一次全量社区聚类（定时兜底纠偏）。"""
    from app.core.llm.resolver import get_optional_client_for_type
    from app.core.memory.clustering.label_propagation import LabelPropagationEngine
    from app.db import neo4j

    engine_db = create_task_engine()
    session_maker = async_sessionmaker(
        engine_db, expire_on_commit=False, class_=AsyncSession
    )
    count = 0
    try:
        async with session_maker() as session:
            result = await session.execute(select(User.id))
            user_ids = [row[0] for row in result.all()]
            for uid in user_ids:
                try:
                    chat_client = await get_optional_client_for_type(
                        session, uid, "chat"
                    )
                    engine = LabelPropagationEngine(chat_client=chat_client)
                    await engine.full_clustering(str(uid))
                    count += 1
                except Exception as e:
                    logger.warning("用户 %s 全量聚类失败: %s", uid, e)
    finally:
        await engine_db.dispose()
        await neo4j.close()
    logger.info("全量社区聚类完成: %d 个用户", count)
    return count


@celery_app.task(name="app.tasks.beat.cluster_communities")
def cluster_communities_task() -> int:
    """全量社区聚类的 Celery 任务入口（定时兜底）。"""
    return asyncio.run(_run_clustering())


async def _run_consolidation() -> int:
    """为所有用户跑一次记忆巩固（短期→长期 + 画像增强）。"""
    from app.core.llm.resolver import get_optional_client_for_type
    from app.core.memory.consolidation.consolidator import ConsolidationEngine
    from app.db import neo4j

    engine_db = create_task_engine()
    session_maker = async_sessionmaker(
        engine_db, expire_on_commit=False, class_=AsyncSession
    )
    count = 0
    try:
        async with session_maker() as session:
            result = await session.execute(select(User.id))
            user_ids = [row[0] for row in result.all()]
            for uid in user_ids:
                try:
                    chat_client = await get_optional_client_for_type(
                        session, uid, "chat"
                    )
                    engine = ConsolidationEngine(chat_client=chat_client)
                    await engine.run(str(uid))
                    count += 1
                except Exception as e:
                    logger.warning("用户 %s 记忆巩固失败: %s", uid, e)
    finally:
        await engine_db.dispose()
        await neo4j.close()
    logger.info("记忆巩固批量完成: %d 个用户", count)
    return count


@celery_app.task(name="app.tasks.beat.consolidate_memory")
def consolidate_memory_task() -> int:
    """记忆巩固的 Celery 任务入口（定时）。"""
    return asyncio.run(_run_consolidation())
