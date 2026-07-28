"""存量数据回填脚本：多知识库上线一次性迁移。

为每个已有用户创建「默认知识库」，把该用户下未归属（kb_id 为空）的
documents / images 归入默认库（PG），并回填 ES chunk 的 kb_id。

幂等：已有默认库则复用；已归属的资料不动；ES 仅回填缺失 kb_id 的 chunk。

运行：
    cd api
    uv run python -m app.db.backfill_kb
"""
import asyncio

from sqlalchemy import select, update

import app.models  # noqa: F401  注册全部 ORM
from app.core.logging import get_logger
from app.core.rag.indexing.es_store import backfill_kb_id
from app.db import elastic
from app.db.postgres import create_task_engine
from app.models.document_model import Document
from app.models.image_model import Image
from app.models.user_model import User
from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)


async def _run() -> None:
    engine = create_task_engine()
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )
    try:
        async with session_maker() as session:
            await _backfill(session)
    finally:
        await engine.dispose()
        await elastic.close()


async def _backfill(session: AsyncSession) -> None:
    kb_repo = KnowledgeBaseRepository(session)
    user_ids = list((await session.execute(select(User.id))).scalars().all())
    logger.info("存量回填：共 %d 个用户", len(user_ids))

    for uid in user_ids:
        kb = await kb_repo.ensure_default(uid)
        # 文档归默认库
        doc_res = await session.execute(
            update(Document)
            .where(Document.user_id == uid, Document.kb_id.is_(None))
            .values(kb_id=kb.id)
        )
        # 图片归默认库
        img_res = await session.execute(
            update(Image)
            .where(Image.user_id == uid, Image.kb_id.is_(None))
            .values(kb_id=kb.id)
        )
        await session.commit()
        # ES chunk 回填
        try:
            es_updated = await backfill_kb_id(str(uid), str(kb.id))
        except Exception as e:
            es_updated = -1
            logger.warning("用户 %s 的 ES 回填失败: %s", uid, e)
        logger.info(
            "用户 %s：默认库=%s 文档归位=%s 图片归位=%s ES回填=%s",
            uid,
            kb.id,
            doc_res.rowcount,
            img_res.rowcount,
            es_updated,
        )

    logger.info("存量回填完成")


if __name__ == "__main__":
    asyncio.run(_run())
