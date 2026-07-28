"""全局搜索业务服务：并行联合检索文档 / 图片 / 记忆，按类型分组返回。

三路并发（asyncio.gather）：
- 文档：ES 混合检索 source_type=document
- 图片：ES 混合检索 source_type=image
- 记忆：Neo4j 图谱混合检索（实体 + 关系）
任一路失败不影响其余（降级返回空）。
"""
import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.llm.resolver import get_client_for_type
from app.core.logging import get_logger
from app.core.memory.retrieval.searcher import search_memory
from app.core.rag.retrieval import hybrid_search

logger = get_logger(__name__)


class SearchService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _search_documents(self, user_id: uuid.UUID, query: str, top_k: int):
        try:
            return await hybrid_search(
                self.session, user_id, query, top_k=top_k, source_type="document",
                min_vector_score=settings.global_search_min_vector_score,
            )
        except Exception as e:
            logger.warning("全局搜索-文档失败: %s", e)
            return []

    async def _search_images(self, user_id: uuid.UUID, query: str, top_k: int):
        try:
            return await hybrid_search(
                self.session, user_id, query, top_k=top_k, source_type="image",
                min_vector_score=settings.global_search_min_vector_score,
            )
        except Exception as e:
            logger.warning("全局搜索-图片失败: %s", e)
            return []

    async def _search_memory(self, user_id: uuid.UUID, query: str, top_k: int):
        try:
            embed_client = await get_client_for_type(
                self.session, user_id, "embedding"
            )
            return await search_memory(
                embed_client=embed_client, user_id=user_id, query=query, top_k=top_k,
                min_vector_score=settings.memory_search_min_vector_score,
            )
        except Exception as e:
            logger.warning("全局搜索-记忆失败: %s", e)
            return []

    async def search_all(
        self, user_id: uuid.UUID, query: str, top_k: int = 8
    ) -> dict:
        """三路并行检索，分组返回 {documents, images, memories}。"""
        query = (query or "").strip()
        if not query:
            return {"documents": [], "images": [], "memories": []}
        documents, images, memories = await asyncio.gather(
            self._search_documents(user_id, query, top_k),
            self._search_images(user_id, query, top_k),
            self._search_memory(user_id, query, top_k),
        )
        return {"documents": documents, "images": images, "memories": memories}
