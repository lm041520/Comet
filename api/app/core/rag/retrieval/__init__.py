"""RAG 检索入口。"""

from app.core.rag.retrieval.search import hybrid_search, hybrid_search_with_trace

__all__ = ["hybrid_search", "hybrid_search_with_trace"]
