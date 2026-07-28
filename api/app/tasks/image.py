"""图片处理 Celery 任务：取图 → 多模态描述 → 描述向量化 → 写 ES。

与文档解析一致，使用任务级独立事件循环资源。
"""
import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.models  # noqa: F401
from app.celery_app import celery_app
from app.core.llm.resolver import get_client_for_type, get_optional_client_for_type
from app.core.logging import get_logger
from app.core.rag.classifier import classify_content
from app.core.rag.indexing.es_index import CHUNK_TYPE_IMAGE
from app.core.rag.indexing.es_store import build_chunk_doc, bulk_index, delete_by_source
from app.core.rag.image_describe import describe_image
from app.core.storage import get_storage
from app.db import elastic
from app.db.postgres import create_task_engine
from app.models.image_model import (
    IMG_STATUS_DONE,
    IMG_STATUS_FAILED,
    IMG_STATUS_PROCESSING,
)
from app.repositories.image_repository import ImageRepository
from app.repositories.tag_repository import TagRepository

logger = get_logger(__name__)


async def _run(image_id: str) -> None:
    img_uuid = uuid.UUID(image_id)
    engine = create_task_engine()
    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_maker() as session:
            await _process(session, image_id, img_uuid)
    finally:
        await engine.dispose()
        await elastic.close()


async def _process(session: AsyncSession, image_id: str, img_uuid: uuid.UUID) -> None:
    repo = ImageRepository(session)
    img = await repo.get_by_id(img_uuid)
    if not img:
        logger.warning("图片任务：图片不存在 %s", image_id)
        return

    try:
        img.status = IMG_STATUS_PROCESSING
        await repo.save(img)

        content = await get_storage().get(img.file_key)

        # 多模态描述（用用户默认多模态模型）
        vision_client = await get_client_for_type(session, img.user_id, "multimodal")
        info = await describe_image(vision_client, content, img.file_ext)

        img.description = info["description"]
        img.ocr_text = info["ocr_text"]
        img.objects = info["objects"]
        img.scene = info["scene"]

        # 描述文本向量化后写 ES（可被搜索）
        searchable = "\n".join(
            filter(None, [info["description"], info["ocr_text"], info["scene"]])
        )
        if searchable.strip():
            embed_client = await get_client_for_type(session, img.user_id, "embedding")
            vector = await embed_client.embed_one(searchable)
            user_id = str(img.user_id)
            await delete_by_source(user_id, image_id)
            await bulk_index(
                [
                    build_chunk_doc(
                        user_id=user_id,
                        source_type="image",
                        source_id=image_id,
                        doc_name=img.file_name,
                        chunk_type=CHUNK_TYPE_IMAGE,
                        content=searchable,
                        vector=vector,
                        kb_id=str(img.kb_id) if img.kb_id else None,
                    )
                ]
            )

        # AI 自动分类打标签（基于描述，失败不阻断）
        await _auto_tag(session, img, searchable)

        img.status = IMG_STATUS_DONE
        img.error_msg = None
        await repo.save(img)
        logger.info("图片处理完成: %s scene=%s", image_id, img.scene)
    except Exception as e:
        logger.error("图片处理失败: %s: %s", image_id, e, exc_info=True)
        img.status = IMG_STATUS_FAILED
        img.error_msg = str(e)[:500]
        await repo.save(img)


async def _auto_tag(session: AsyncSession, img, text: str) -> None:
    if not text.strip():
        return
    chat_client = await get_optional_client_for_type(session, img.user_id, "chat")
    if not chat_client:
        return
    tag_repo = TagRepository(session)
    existing = [t.name for t in await tag_repo.list_by_user(img.user_id)]
    tag_names = await classify_content(chat_client, text, existing)
    if not tag_names:
        return
    tag_ids = []
    for name in tag_names:
        tag = await tag_repo.get_or_create(img.user_id, name)
        tag_ids.append(tag.id)
    await tag_repo.set_image_tags(img.id, tag_ids)


@celery_app.task(name="app.tasks.image.process_image")
def process_image_task(image_id: str) -> str:
    asyncio.run(_run(image_id))
    return image_id
