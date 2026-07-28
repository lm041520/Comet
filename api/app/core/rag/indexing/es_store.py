"""comet_chunks 索引的写入与删除。"""

import uuid
from datetime import datetime, timezone

from elasticsearch import helpers

from app.core.logging import get_logger
from app.core.rag.indexing.es_index import CHUNKS_INDEX
from app.db.elastic import get_es

logger = get_logger(__name__)


def build_chunk_doc(
    *,
    user_id: str,
    source_type: str,
    source_id: str,
    doc_name: str,
    chunk_type: str,
    content: str,
    vector: list[float] | None,
    parent_id: str | None = None,
    tags: list[str] | None = None,
    kb_id: str | None = None,
    block_ids: list[str] | None = None,
    block_types: list[str] | None = None,
    page_start: int | None = None,
    page_end: int | None = None,
    heading_path: list[str] | None = None,
    chunk_index: int = 0,
    parser_name: str | None = None,
) -> dict:
    """构造一条 ES chunk 文档。"""
    chunk_id = uuid.uuid4().hex
    return {
        "_index": CHUNKS_INDEX,
        "_id": chunk_id,
        "_source": {
            "user_id": user_id,
            "kb_id": kb_id,
            "source_type": source_type,
            "source_id": source_id,
            "doc_name": doc_name,
            "chunk_id": chunk_id,
            "chunk_type": chunk_type,
            "parent_id": parent_id,
            "block_ids": block_ids or [],
            "block_types": block_types or [],
            "page_start": page_start,
            "page_end": page_end,
            "heading_path": heading_path or [],
            "chunk_index": chunk_index,
            "parser_name": parser_name,
            "content": content,
            "tags": tags or [],
            "vector": vector,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    }


async def bulk_index(docs: list[dict]) -> int:
    """批量写入 chunk 文档，返回成功条数。"""
    if not docs:
        return 0
    es = get_es()
    success, _ = await helpers.async_bulk(es, docs)
    await es.indices.refresh(index=CHUNKS_INDEX)
    logger.info("ES 批量写入 %d 条 chunk", success)
    return success


async def delete_by_source(user_id: str, source_id: str) -> int:
    """删除某来源（文档/图片）的所有 chunk。删除文档时同步清理。"""
    es = get_es()
    resp = await es.delete_by_query(
        index=CHUNKS_INDEX,
        body={
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"user_id": user_id}},
                        {"term": {"source_id": source_id}},
                    ]
                }
            }
        },
        refresh=True,
    )
    deleted = resp.get("deleted", 0)
    logger.info("ES 删除 source=%s 的 %d 条 chunk", source_id, deleted)
    return deleted


async def update_tags_by_source(user_id: str, source_id: str, tags: list[str]) -> None:
    """更新某来源所有 chunk 的 tags（AI 分类后回写）。"""
    es = get_es()
    await es.update_by_query(
        index=CHUNKS_INDEX,
        body={
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"user_id": user_id}},
                        {"term": {"source_id": source_id}},
                    ]
                }
            },
            "script": {
                "source": "ctx._source.tags = params.tags",
                "params": {"tags": tags},
            },
        },
        refresh=True,
    )


async def update_kb_by_source(user_id: str, source_id: str, kb_id: str) -> None:
    """更新某来源所有 chunk 的 kb_id（文档/图片移动到其他知识库后回写）。"""
    es = get_es()
    await es.update_by_query(
        index=CHUNKS_INDEX,
        body={
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"user_id": user_id}},
                        {"term": {"source_id": source_id}},
                    ]
                }
            },
            "script": {
                "source": "ctx._source.kb_id = params.kb_id",
                "params": {"kb_id": kb_id},
            },
        },
        refresh=True,
    )


async def backfill_kb_id(user_id: str, kb_id: str) -> int:
    """把该用户所有缺失 kb_id 的 chunk 回填为默认库 id（存量迁移用）。返回更新条数。"""
    es = get_es()
    resp = await es.update_by_query(
        index=CHUNKS_INDEX,
        body={
            "query": {
                "bool": {
                    "filter": [{"term": {"user_id": user_id}}],
                    "must_not": [{"exists": {"field": "kb_id"}}],
                }
            },
            "script": {
                "source": "ctx._source.kb_id = params.kb_id",
                "params": {"kb_id": kb_id},
            },
        },
        refresh=True,
    )
    updated = resp.get("updated", 0)
    logger.info("ES 回填 user=%s 缺失 kb_id 的 %d 条 chunk", user_id, updated)
    return updated
