"""Elasticsearch Chunk 索引定义与读写。"""

from app.core.rag.indexing.es_index import (
    CHUNKS_INDEX,
    CHUNK_TYPE_CHILD,
    CHUNK_TYPE_IMAGE,
    CHUNK_TYPE_PARENT,
    ensure_index,
)
from app.core.rag.indexing.es_store import (
    build_chunk_doc,
    bulk_index,
    delete_by_source,
    update_tags_by_source,
)

__all__ = [
    "CHUNKS_INDEX",
    "CHUNK_TYPE_CHILD",
    "CHUNK_TYPE_IMAGE",
    "CHUNK_TYPE_PARENT",
    "build_chunk_doc",
    "bulk_index",
    "delete_by_source",
    "ensure_index",
    "update_tags_by_source",
]
