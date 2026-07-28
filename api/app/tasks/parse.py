"""文档解析 Celery 任务：取文件 → 解析 → 父子分块 → 向量化 → 写 ES。

Celery 任务为同步入口，内部用 asyncio.run 跑异步流程。
每个任务使用独立的事件循环，需用任务级 DB 引擎并重置 ES 客户端，
避免全局单例绑定到已关闭的旧事件循环。
"""
import asyncio
import hashlib
import uuid
from datetime import datetime, timezone
from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.models  # noqa: F401  确保所有 ORM 模型注册到 metadata
from app.celery_app import celery_app
from app.config import settings
from app.core.llm.resolver import get_client_for_type, get_optional_client_for_type
from app.core.logging import get_logger
from app.core.rag.chunking import chunk_blocks
from app.core.rag.classifier import classify_content
from app.core.rag.indexing.es_index import CHUNK_TYPE_CHILD, CHUNK_TYPE_PARENT
from app.core.rag.indexing.es_store import (
    build_chunk_doc,
    bulk_index,
    delete_by_source,
    update_tags_by_source,
)
from app.core.rag.ingestion import parse_document_structured
from app.core.storage import get_storage
from app.db import elastic
from app.db.postgres import create_task_engine
from app.models.document_model import (
    DOC_STATUS_DONE,
    DOC_STATUS_FAILED,
    DOC_STATUS_PARSING,
)
from app.repositories.document_block_repository import DocumentBlockRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.tag_repository import TagRepository

logger = get_logger(__name__)


async def _run(document_id: str) -> None:
    doc_uuid = uuid.UUID(document_id)
    engine = create_task_engine()
    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_maker() as session:
            await _parse(session, document_id, doc_uuid)
    finally:
        await engine.dispose()
        # 关闭本任务事件循环内创建的 ES 客户端
        await elastic.close()


async def _parse(session: AsyncSession, document_id: str, doc_uuid: uuid.UUID) -> None:
    repo = DocumentRepository(session)
    block_repo = DocumentBlockRepository(session)
    doc = await repo.get_by_id(doc_uuid)
    if not doc:
        logger.warning("解析任务：文档不存在 %s", document_id)
        return

    started_at = perf_counter()
    try:
        doc.status = DOC_STATUS_PARSING
        doc.progress = 0.1
        await repo.save(doc)

        # 1. 取文件
        content = await get_storage().get(doc.file_key)
        doc.content_hash = hashlib.sha256(content).hexdigest()
        # 2. 解析为纯文本
        parsed = parse_document_structured(
            doc.file_ext,
            content,
            preferred_parser=doc.preferred_parser,
        )
        text = parsed.text
        if not text.strip():
            raise ValueError("解析结果为空")
        await block_repo.replace_for_document(doc.id, parsed.blocks)
        doc.parser_name = parsed.parser_name
        doc.parser_version = parsed.parser_version
        doc.parse_status = parsed.status.value
        doc.parse_summary = {
            **parsed.parse_summary,
            "page_count": parsed.profile.page_count if parsed.profile else None,
            "warnings": parsed.warnings,
            "file_size": len(content),
            "image_count": parsed.profile.image_count if parsed.profile else 0,
            "ocr_used": bool(
                parsed.parser_name == "docling"
                and parsed.profile
                and parsed.profile.scanned_pdf_risk
            ),
        }
        doc.progress = 0.3
        await repo.save(doc)

        # 3. Block 感知父子分块
        parents = chunk_blocks(parsed.blocks)
        if not parents:
            raise ValueError("分块结果为空")

        # 4. 子块向量化（用用户默认 embedding 模型）
        embed_client = await get_client_for_type(session, doc.user_id, "embedding")
        user_id = str(doc.user_id)
        kb_id = str(doc.kb_id) if doc.kb_id else None
        es_docs: list[dict] = []
        chunk_total = 0
        for parent in parents:
            parent_doc = build_chunk_doc(
                user_id=user_id,
                source_type="document",
                source_id=document_id,
                doc_name=doc.file_name,
                chunk_type=CHUNK_TYPE_PARENT,
                content=parent.content,
                vector=None,
                kb_id=kb_id,
                block_ids=parent.block_ids,
                block_types=parent.block_types,
                page_start=parent.page_start,
                page_end=parent.page_end,
                heading_path=parent.heading_path,
                chunk_index=parent.chunk_index,
                parser_name=parsed.parser_name,
            )
            parent_chunk_id = parent_doc["_id"]
            es_docs.append(parent_doc)

            if parent.child_chunks:
                vectors = await embed_client.embed(parent.children)
                for child, vec in zip(parent.child_chunks, vectors):
                    es_docs.append(
                        build_chunk_doc(
                            user_id=user_id,
                            source_type="document",
                            source_id=document_id,
                            doc_name=doc.file_name,
                            chunk_type=CHUNK_TYPE_CHILD,
                            content=child.content,
                            vector=vec,
                            parent_id=parent_chunk_id,
                            kb_id=kb_id,
                            block_ids=child.block_ids,
                            block_types=child.block_types,
                            page_start=child.page_start,
                            page_end=child.page_end,
                            heading_path=child.heading_path,
                            chunk_index=child.chunk_index,
                            parser_name=parsed.parser_name,
                        )
                    )
                    chunk_total += 1
        doc.progress = 0.8
        await repo.save(doc)

        # 5. 写 ES（先清旧 chunk，支持重试幂等）
        await delete_by_source(user_id, document_id)
        await bulk_index(es_docs)

        # 6. AI 自动分类打标签（有对话模型才做，失败不阻断）
        await _auto_tag(session, doc, text)

        doc.status = DOC_STATUS_DONE
        doc.progress = 1.0
        doc.chunk_num = chunk_total
        doc.error_msg = None
        doc.parsed_at = datetime.now(timezone.utc)
        doc.parse_summary = {
            **(doc.parse_summary or {}),
            "parent_chunk_count": len(parents),
            "child_chunk_count": chunk_total,
            "parse_duration_ms": round((perf_counter() - started_at) * 1000),
        }
        await repo.save(doc)
        logger.info("文档解析完成: %s chunks=%d", document_id, chunk_total)
    except Exception as e:
        logger.error("文档解析失败: %s: %s", document_id, e, exc_info=True)
        doc.status = DOC_STATUS_FAILED
        doc.error_msg = str(e)[:500]
        doc.parse_status = "failed"
        doc.parse_summary = {
            **(doc.parse_summary or {}),
            "error": str(e)[:500],
            "parse_duration_ms": round((perf_counter() - started_at) * 1000),
        }
        await repo.save(doc)


async def _auto_tag(session: AsyncSession, doc, text: str) -> None:
    """用对话模型给文档分类，写回 PG（关联）与 ES（chunk tags）。"""
    chat_client = await get_optional_client_for_type(session, doc.user_id, "chat")
    if not chat_client:
        return
    tag_repo = TagRepository(session)
    existing = [t.name for t in await tag_repo.list_by_user(doc.user_id)]
    tag_names = await classify_content(chat_client, text, existing)
    if not tag_names:
        return
    tag_ids = []
    for name in tag_names:
        tag = await tag_repo.get_or_create(doc.user_id, name)
        tag_ids.append(tag.id)
    await tag_repo.set_document_tags(doc.id, tag_ids)
    await update_tags_by_source(str(doc.user_id), str(doc.id), tag_names)


@celery_app.task(
    name="app.tasks.parse.parse_document",
    time_limit=settings.rag_parse_time_limit_seconds,
)
def parse_document_task(document_id: str) -> str:
    """解析文档的 Celery 任务入口。"""
    asyncio.run(_run(document_id))
    return document_id
