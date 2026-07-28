"""RAG Elasticsearch 索引定义与初始化。

统一索引 comet_chunks（个人版数据量小，单索引 + user_id 过滤足够）。
向量维度固定 1024（通义 text-embedding-v3）。
"""

from app.config import settings
from app.core.logging import get_logger
from app.db.elastic import get_es

logger = get_logger(__name__)

CHUNKS_INDEX = "comet_chunks"
VECTOR_DIMS = settings.embedding_dims

# 父子分块：child 用于向量召回，parent 提供更大上下文
CHUNK_TYPE_CHILD = "child"
CHUNK_TYPE_PARENT = "parent"
CHUNK_TYPE_IMAGE = "image_desc"

_MAPPING = {
    "mappings": {
        "properties": {
            "user_id": {"type": "keyword"},
            "kb_id": {"type": "keyword"},  # 所属知识库（多知识库检索范围过滤）
            "source_type": {"type": "keyword"},  # document | image
            "source_id": {"type": "keyword"},  # documents.id / images.id
            "doc_name": {"type": "keyword"},
            "chunk_id": {"type": "keyword"},
            "chunk_type": {"type": "keyword"},  # child | parent | image_desc
            "parent_id": {"type": "keyword"},  # child 指向其 parent chunk_id
            "block_ids": {"type": "keyword"},
            "block_types": {"type": "keyword"},
            "page_start": {"type": "integer"},
            "page_end": {"type": "integer"},
            "heading_path": {"type": "keyword"},
            "chunk_index": {"type": "integer"},
            "parser_name": {"type": "keyword"},
            # content 用 IK 中文分词：写入 ik_max_word（细粒度），查询 ik_smart（粗粒度）
            "content": {
                "type": "text",
                "analyzer": "ik_max_word",
                "search_analyzer": "ik_smart",
            },
            "tags": {"type": "keyword"},
            "vector": {
                "type": "dense_vector",
                "dims": VECTOR_DIMS,
                "index": True,
                "similarity": "cosine",
            },
            "created_at": {"type": "date"},
        }
    },
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
    },
}


async def ensure_index() -> None:
    """确保 comet_chunks 索引存在且 kb_id 为 keyword 类型。

    - 不存在：按正确 mapping 创建。
    - 已存在但 kb_id 缺失：put_mapping 补字段。
    - 已存在但 kb_id 是错误类型（旧索引被动态映射成 text）：ES 不允许原地改类型，
      自动 reindex 重建（数据量小，个人项目可接受），修复后多库检索过滤才生效。
    """
    es = get_es()
    exists = await es.indices.exists(index=CHUNKS_INDEX)
    if not exists:
        await es.indices.create(index=CHUNKS_INDEX, body=_MAPPING)
        logger.info("创建 ES 索引: %s", CHUNKS_INDEX)
        return

    await _ensure_structured_fields(es)

    # 已存在：检查 kb_id 字段类型
    kb_type = await _kb_id_type(es)
    if kb_type == "keyword":
        return  # 已正确，无需处理
    if kb_type is None:
        # 字段缺失：增量补齐（不影响存量）
        try:
            await es.indices.put_mapping(
                index=CHUNKS_INDEX,
                body={"properties": {"kb_id": {"type": "keyword"}}},
            )
            logger.info("ES 索引已存在，已补齐 kb_id 字段: %s", CHUNKS_INDEX)
        except Exception as e:
            logger.warning("补齐 ES kb_id 字段失败（忽略）: %s", e)
        return
    # 类型不对（多为 text）：reindex 重建
    logger.warning(
        "ES 索引 %s 的 kb_id 类型为 %s（应为 keyword），开始自动 reindex 修复…",
        CHUNKS_INDEX,
        kb_type,
    )
    try:
        await _rebuild_index_fix_kb_id(es)
        logger.info("ES 索引 kb_id 类型修复完成: %s", CHUNKS_INDEX)
    except Exception as e:
        logger.error("ES 索引 kb_id 修复失败（多库检索过滤将不生效）: %s", e, exc_info=True)


async def _kb_id_type(es) -> str | None:
    """读取 comet_chunks 当前 kb_id 字段类型；不存在返回 None。"""
    try:
        resp = await es.indices.get_mapping(index=CHUNKS_INDEX)
        props = resp[CHUNKS_INDEX]["mappings"].get("properties", {})
        field = props.get("kb_id")
        return field.get("type") if field else None
    except Exception as e:
        logger.warning("读取 ES mapping 失败: %s", e)
        return None


async def _ensure_structured_fields(es) -> None:
    """为存量索引增量补齐 Block 追溯字段。"""
    properties = {
        name: config
        for name, config in _MAPPING["mappings"]["properties"].items()
        if name
        in {
            "block_ids",
            "block_types",
            "page_start",
            "page_end",
            "heading_path",
            "chunk_index",
            "parser_name",
        }
    }
    try:
        await es.indices.put_mapping(
            index=CHUNKS_INDEX,
            body={"properties": properties},
        )
    except Exception as exc:
        logger.warning("补齐 ES Block 追溯字段失败: %s", exc)


async def _rebuild_index_fix_kb_id(es) -> None:
    """通过临时索引 reindex，把 comet_chunks 用正确 mapping 重建。

    流程：建临时索引(正确 mapping) → reindex 原→临时 → 删原 → 重建原(正确 mapping)
    → reindex 临时→原 → 删临时。数据量小，串行同步等待。
    """
    tmp_index = f"{CHUNKS_INDEX}_reindex_tmp"
    # 清理可能残留的临时索引
    if await es.indices.exists(index=tmp_index):
        await es.indices.delete(index=tmp_index)
    # 1) 建临时索引（正确 mapping）
    await es.indices.create(index=tmp_index, body=_MAPPING)
    # 2) 原 → 临时（refresh 确保数据落盘后再删原索引）
    await es.reindex(
        body={"source": {"index": CHUNKS_INDEX}, "dest": {"index": tmp_index}},
        refresh=True,
        wait_for_completion=True,
    )
    # 3) 删原索引，按正确 mapping 重建
    await es.indices.delete(index=CHUNKS_INDEX)
    await es.indices.create(index=CHUNKS_INDEX, body=_MAPPING)
    # 4) 临时 → 原
    await es.reindex(
        body={"source": {"index": tmp_index}, "dest": {"index": CHUNKS_INDEX}},
        refresh=True,
        wait_for_completion=True,
    )
    # 5) 删临时索引
    await es.indices.delete(index=tmp_index)


__all__ = [
    "CHUNKS_INDEX",
    "VECTOR_DIMS",
    "CHUNK_TYPE_CHILD",
    "CHUNK_TYPE_PARENT",
    "CHUNK_TYPE_IMAGE",
    "ensure_index",
]
