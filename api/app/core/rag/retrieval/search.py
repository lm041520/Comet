"""混合检索与可解释检索 Trace。"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm.resolver import get_client_for_type, get_optional_client_for_type
from app.core.logging import get_logger
from app.core.rag.indexing.es_index import CHUNK_TYPE_CHILD, CHUNK_TYPE_IMAGE, CHUNKS_INDEX
from app.db.elastic import get_es
from app.repositories.document_block_repository import DocumentBlockRepository
from app.repositories.document_repository import DocumentRepository

logger = get_logger(__name__)

_VECTOR_WEIGHT = 0.6
_BM25_WEIGHT = 0.4


def _normalize(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    values = list(scores.values())
    low, high = min(values), max(values)
    if high - low < 1e-9:
        return {key: 1.0 for key in scores}
    return {key: (value - low) / (high - low) for key, value in scores.items()}


def _rank_map(scores: dict[str, float]) -> dict[str, int]:
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return {chunk_id: index + 1 for index, (chunk_id, _score) in enumerate(ordered)}


def _round(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None


async def hybrid_search(
    session: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    top_k: int = 5,
    recall_size: int = 20,
    tags: list[str] | None = None,
    source_type: str | None = None,
    min_vector_score: float | None = None,
    kb_ids: list[str] | None = None,
) -> list[dict]:
    """执行混合检索，返回兼容业务调用方的结果。"""
    trace = await _run_hybrid_search(
        session,
        user_id,
        query,
        top_k=top_k,
        recall_size=recall_size,
        tags=tags,
        source_type=source_type,
        min_vector_score=min_vector_score,
        kb_ids=kb_ids,
    )
    return [
        {
            "chunk_id": item["chunk_id"],
            "content": item["parent_content"],
            "matched_content": item["child_content"],
            "doc_name": item["doc_name"],
            "source_id": item["source_id"],
            "source_type": item["source_type"],
            "kb_id": item["kb_id"],
            "score": item["score"],
            "block_ids": item["block_ids"],
            "block_types": item["block_types"],
            "page_start": item["page_start"],
            "page_end": item["page_end"],
            "heading_path": item["heading_path"],
            "parser_name": item["parser_name"],
        }
        for item in trace["results"]
    ]


async def hybrid_search_with_trace(
    session: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    *,
    kb_id: uuid.UUID,
    top_k: int = 8,
    recall_size: int = 20,
) -> dict[str, Any]:
    """在单个知识库内检索，并回取 Block、解析信息和阶段分数。"""
    trace = await _run_hybrid_search(
        session,
        user_id,
        query,
        top_k=top_k,
        recall_size=max(recall_size, top_k),
        source_type="document",
        kb_ids=[str(kb_id)],
    )
    results = trace["results"]

    block_ids: list[uuid.UUID] = []
    document_ids: list[uuid.UUID] = []
    for item in results:
        for block_id in item["block_ids"]:
            try:
                block_ids.append(uuid.UUID(block_id))
            except (TypeError, ValueError):
                continue
        try:
            document_ids.append(uuid.UUID(item["source_id"]))
        except (TypeError, ValueError):
            continue

    blocks = await DocumentBlockRepository(session).get_many(
        user_id,
        list(dict.fromkeys(block_ids)),
        kb_id,
    )
    documents = await DocumentRepository(session).get_many(
        user_id,
        list(dict.fromkeys(document_ids)),
        kb_id,
    )
    block_map = {str(block.id): block for block in blocks}
    document_map = {str(document.id): document for document in documents}

    for item in results:
        item["blocks"] = [
            {
                "block_id": str(block.id),
                "block_order": block.block_order,
                "block_type": block.block_type,
                "content": block.content,
                "page_start": block.page_start,
                "page_end": block.page_end,
                "heading_path": block.heading_path or [],
                "extra_json": block.extra_json or {},
            }
            for block_id in item["block_ids"]
            if (block := block_map.get(block_id)) is not None
        ]
        document = document_map.get(item["source_id"])
        summary = document.parse_summary if document else {}
        item["warnings"] = list((summary or {}).get("warnings", []))
        if document:
            item["parser_name"] = document.parser_name or item["parser_name"]
            item["parser_version"] = document.parser_version
            item["parse_status"] = document.parse_status
        else:
            item["parser_version"] = None
            item["parse_status"] = None

    return {
        "query": query,
        "kb_id": str(kb_id),
        "top_k": top_k,
        "recall_size": max(recall_size, top_k),
        "vector_weight": _VECTOR_WEIGHT,
        "bm25_weight": _BM25_WEIGHT,
        "rerank_used": trace["rerank_used"],
        "rerank_error": trace["rerank_error"],
        "results": results,
    }


async def _run_hybrid_search(
    session: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    *,
    top_k: int,
    recall_size: int,
    tags: list[str] | None = None,
    source_type: str | None = None,
    min_vector_score: float | None = None,
    kb_ids: list[str] | None = None,
) -> dict[str, Any]:
    if kb_ids == []:
        return {"rerank_used": False, "rerank_error": None, "results": []}

    es = get_es()
    user_id_text = str(user_id)
    if source_type == "image":
        chunk_types = [CHUNK_TYPE_IMAGE]
    elif source_type == "document":
        chunk_types = [CHUNK_TYPE_CHILD]
    else:
        chunk_types = [CHUNK_TYPE_CHILD, CHUNK_TYPE_IMAGE]

    base_filter: list[dict] = [
        {"term": {"user_id": user_id_text}},
        {"terms": {"chunk_type": chunk_types}},
    ]
    if kb_ids is not None:
        base_filter.append({"terms": {"kb_id": kb_ids}})
    if tags:
        base_filter.append({"terms": {"tags": tags}})
    if source_type:
        base_filter.append({"term": {"source_type": source_type}})

    embed_client = await get_client_for_type(session, user_id, "embedding")
    query_vector = await embed_client.embed_one(query)
    knn_response = await es.search(
        index=CHUNKS_INDEX,
        body={
            "size": recall_size,
            "query": {"bool": {"filter": base_filter}},
            "knn": {
                "field": "vector",
                "query_vector": query_vector,
                "k": recall_size,
                "num_candidates": recall_size * 5,
                "filter": {"bool": {"filter": base_filter}},
            },
        },
    )
    bm25_response = await es.search(
        index=CHUNKS_INDEX,
        body={
            "size": recall_size,
            "query": {
                "bool": {
                    "must": [{"match": {"content": query}}],
                    "filter": base_filter,
                }
            },
        },
    )

    hits: dict[str, dict] = {}
    vector_raw: dict[str, float] = {}
    bm25_raw: dict[str, float] = {}
    for hit in knn_response["hits"]["hits"]:
        hits[hit["_id"]] = hit["_source"]
        vector_raw[hit["_id"]] = float(hit["_score"])
    for hit in bm25_response["hits"]["hits"]:
        hits[hit["_id"]] = hit["_source"]
        bm25_raw[hit["_id"]] = float(hit["_score"])

    vector_normalized = _normalize(vector_raw)
    bm25_normalized = _normalize(bm25_raw)
    fusion_scores = {
        chunk_id: (
            _VECTOR_WEIGHT * vector_normalized.get(chunk_id, 0.0)
            + _BM25_WEIGHT * bm25_normalized.get(chunk_id, 0.0)
        )
        for chunk_id in hits
    }
    vector_cosine = {chunk_id: 2.0 * score - 1.0 for chunk_id, score in vector_raw.items()}

    rerank_used = False
    rerank_error: str | None = None
    rerank_scores: dict[str, float] = {}
    if min_vector_score is not None:
        filtered_scores = {
            chunk_id: score
            for chunk_id, score in vector_cosine.items()
            if score >= min_vector_score
        }
        candidate_ids = [
            chunk_id
            for chunk_id, _score in sorted(
                filtered_scores.items(), key=lambda item: item[1], reverse=True
            )[:top_k]
        ]
    else:
        candidate_ids = [
            chunk_id
            for chunk_id, _score in sorted(
                fusion_scores.items(), key=lambda item: item[1], reverse=True
            )[: max(top_k, recall_size)]
        ]
        rerank_client = await get_optional_client_for_type(session, user_id, "rerank")
        if rerank_client and candidate_ids:
            try:
                reranked = await rerank_client.rerank(
                    query,
                    [hits[chunk_id]["content"] for chunk_id in candidate_ids],
                    top_n=top_k,
                )
                rerank_scores = {candidate_ids[index]: float(score) for index, score in reranked}
                candidate_ids = [candidate_ids[index] for index, _score in reranked]
                rerank_used = True
            except Exception as exc:
                rerank_error = str(exc)[:300]
                logger.warning("rerank 失败，回退加权融合排序: %s", exc)

    vector_ranks = _rank_map(vector_raw)
    bm25_ranks = _rank_map(bm25_raw)
    fusion_ranks = _rank_map(fusion_scores)
    results: list[dict[str, Any]] = []
    for final_index, chunk_id in enumerate(candidate_ids[:top_k]):
        source = hits[chunk_id]
        parent_id, parent_content = await _resolve_parent(
            es,
            user_id_text,
            source,
        )
        if min_vector_score is not None:
            score = vector_cosine.get(chunk_id, 0.0)
        else:
            score = fusion_scores.get(chunk_id, 0.0)
        results.append(
            {
                "rank": final_index + 1,
                "chunk_id": chunk_id,
                "parent_id": parent_id,
                "child_content": source.get("content", ""),
                "parent_content": parent_content,
                "doc_name": source.get("doc_name"),
                "source_id": source.get("source_id"),
                "source_type": source.get("source_type"),
                "kb_id": source.get("kb_id"),
                "score": _round(score),
                "scores": {
                    "vector_score": _round(vector_cosine.get(chunk_id)),
                    "vector_es_score": _round(vector_raw.get(chunk_id)),
                    "vector_normalized": _round(vector_normalized.get(chunk_id)),
                    "bm25_score": _round(bm25_raw.get(chunk_id)),
                    "bm25_normalized": _round(bm25_normalized.get(chunk_id)),
                    "fusion_score": _round(fusion_scores.get(chunk_id)),
                    "rerank_score": _round(rerank_scores.get(chunk_id)),
                },
                "stage_ranks": {
                    "vector_rank": vector_ranks.get(chunk_id),
                    "bm25_rank": bm25_ranks.get(chunk_id),
                    "fusion_rank": fusion_ranks.get(chunk_id),
                    "final_rank": final_index + 1,
                },
                "block_ids": source.get("block_ids", []),
                "block_types": source.get("block_types", []),
                "page_start": source.get("page_start"),
                "page_end": source.get("page_end"),
                "heading_path": source.get("heading_path", []),
                "chunk_index": source.get("chunk_index", 0),
                "parser_name": source.get("parser_name"),
            }
        )
    return {
        "rerank_used": rerank_used,
        "rerank_error": rerank_error,
        "results": results,
    }


async def _resolve_parent(es, user_id: str, child_source: dict) -> tuple[str | None, str]:
    """命中子块时取父块内容；取不到则返回子块本身。"""
    parent_id = child_source.get("parent_id")
    if not parent_id:
        return None, child_source.get("content", "")
    response = await es.search(
        index=CHUNKS_INDEX,
        body={
            "size": 1,
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"user_id": user_id}},
                        {"term": {"chunk_id": parent_id}},
                    ]
                }
            },
        },
    )
    documents = response["hits"]["hits"]
    if documents:
        return parent_id, documents[0]["_source"].get("content", "")
    return parent_id, child_source.get("content", "")
