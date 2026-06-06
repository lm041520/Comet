"""记忆业务服务：主动记住、记忆列表/详情/删除。

「主动记住」流程：建 memories 记录(status=pending) → 立即返回 → 派发 Celery 萃取任务。
萃取任务完成后回写 status 与图谱溯源统计。
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError
from app.core.logging import get_logger
from app.models.memory_model import (
    MEMORY_SOURCE_MANUAL,
    MEMORY_STATUS_PENDING,
    Memory,
)
from app.repositories.memory_repository import MemoryRepository

logger = get_logger(__name__)


class MemoryService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = MemoryRepository(session)

    async def remember(self, user_id: uuid.UUID, text: str) -> Memory:
        """主动记住：落库 + 派发异步萃取任务。"""
        text = (text or "").strip()
        if not text:
            raise BizError("记忆内容不能为空", code=3001)
        memory = Memory(
            user_id=user_id,
            raw_text=text,
            source=MEMORY_SOURCE_MANUAL,
            status=MEMORY_STATUS_PENDING,
        )
        memory = await self.repo.create(memory)
        # 派发异步萃取（worker 起 memory 队列）
        from app.tasks.memory import extract_memory_task

        extract_memory_task.delay(str(memory.id))
        logger.info("主动记住已提交萃取: memory=%s", memory.id)
        return memory

    async def get_detail(self, user_id: uuid.UUID, memory_id: uuid.UUID) -> Memory:
        memory = await self.repo.get_by_id(memory_id)
        if not memory or memory.user_id != user_id:
            raise BizError("记忆不存在", code=3002, status_code=404)
        return memory

    async def list_memories(
        self, user_id: uuid.UUID, page: int, page_size: int
    ) -> tuple[list[Memory], int]:
        return await self.repo.list_by_user(user_id, page, page_size)

    async def delete(self, user_id: uuid.UUID, memory_id: uuid.UUID) -> None:
        memory = await self.get_detail(user_id, memory_id)
        await self.repo.delete(memory)

    async def search(
        self, user_id: uuid.UUID, query: str, top_k: int = 10
    ) -> list[dict]:
        """记忆检索：图谱混合检索（向量+全文+邻居遍历）。"""
        from app.core.llm.resolver import get_client_for_type
        from app.core.memory.retrieval.searcher import search_memory

        embed_client = await get_client_for_type(self.session, user_id, "embedding")
        return await search_memory(
            embed_client=embed_client, user_id=user_id, query=query, top_k=top_k
        )

    async def get_profile(self, user_id: uuid.UUID) -> dict:
        """画像视图：图谱实体按类型分组 + 类型计数。"""
        from app.repositories.neo4j.memory_graph_repository import (
            MemoryGraphRepository,
        )

        repo = MemoryGraphRepository()
        uid = str(user_id)
        entities = await repo.list_all_entities(uid)
        counts = await repo.entity_type_counts(uid)

        groups: dict[str, list[dict]] = {}
        for e in entities:
            item = {
                "id": e.get("id"),
                "name": e.get("name"),
                "type": e.get("type"),
                "description": e.get("description") or "",
                "aliases": e.get("aliases") or [],
                "relations": e.get("relations") or [],
                "importance": e.get("importance", 0.5),
                "memory_layer": e.get("memory_layer") or "short_term",
                "access_count": e.get("access_count", 0),
                "mention_count": e.get("mention_count", 1),
                "core_facts": e.get("core_facts") or [],
                "traits": e.get("traits") or [],
            }
            groups.setdefault(item["type"], []).append(item)

        return {
            "total": len(entities),
            "type_counts": {c["type"]: c["cnt"] for c in counts},
            "groups": [
                {"type": t, "entities": items} for t, items in groups.items()
            ],
        }

    async def delete_entity(self, user_id: uuid.UUID, entity_id: str) -> None:
        """删除单个图谱实体（连带关系）。"""
        from app.repositories.neo4j.memory_graph_repository import (
            MemoryGraphRepository,
        )

        await MemoryGraphRepository().delete_entity(str(user_id), entity_id)

    async def list_communities(self, user_id: uuid.UUID) -> list[dict]:
        """社区列表（名称/摘要/成员数）。"""
        from app.repositories.neo4j.community_repository import CommunityRepository

        return await CommunityRepository().list_communities(str(user_id))

    async def community_members(
        self, user_id: uuid.UUID, community_id: str
    ) -> list[dict]:
        """某社区的成员实体。"""
        from app.repositories.neo4j.community_repository import CommunityRepository

        members = await CommunityRepository().get_members(str(user_id), community_id)
        return [
            {
                "id": m.get("id"),
                "name": m.get("name"),
                "type": m.get("type"),
                "description": m.get("description") or "",
                "aliases": m.get("aliases") or [],
            }
            for m in members
        ]

    async def recluster(self, user_id: uuid.UUID) -> None:
        """手动触发全量社区聚类（先合并历史重复实体，再聚类）。"""
        from app.core.llm.resolver import get_optional_client_for_type
        from app.core.memory.clustering.label_propagation import (
            LabelPropagationEngine,
        )

        await self.merge_duplicates(user_id)
        chat_client = await get_optional_client_for_type(self.session, user_id, "chat")
        await LabelPropagationEngine(chat_client=chat_client).full_clustering(
            str(user_id)
        )

    async def merge_duplicates(self, user_id: uuid.UUID) -> int:
        """合并历史重复实体（同名同类型只保留一个图节点）。"""
        from app.repositories.neo4j.memory_graph_repository import (
            MemoryGraphRepository,
        )

        return await MemoryGraphRepository().merge_duplicate_entities(str(user_id))

    async def consolidate(self, user_id: uuid.UUID) -> dict:
        """手动触发记忆巩固（短期→长期 + 画像增强）。"""
        from app.core.llm.resolver import get_optional_client_for_type
        from app.core.memory.consolidation.consolidator import ConsolidationEngine

        chat_client = await get_optional_client_for_type(self.session, user_id, "chat")
        return await ConsolidationEngine(chat_client=chat_client).run(str(user_id))

    async def get_graph(self, user_id: uuid.UUID) -> dict:
        """知识图谱全量数据：nodes（实体）+ edges（关系）+ communities。"""
        from app.repositories.neo4j.community_repository import CommunityRepository
        from app.repositories.neo4j.memory_graph_repository import (
            MemoryGraphRepository,
        )

        uid = str(user_id)
        repo = MemoryGraphRepository()
        raw_nodes = await repo.graph_nodes(uid)
        raw_edges = await repo.graph_edges(uid)
        communities = await CommunityRepository().list_communities(uid)

        nodes = [
            {
                "id": n.get("id"),
                "name": n.get("name"),
                "type": n.get("type"),
                "description": n.get("description") or "",
                "community_id": n.get("community_id"),
                "importance": n.get("importance", 0.5),
                "memory_layer": n.get("memory_layer") or "short_term",
                "access_count": n.get("access_count", 0),
                "mention_count": n.get("mention_count", 1),
                "aliases": n.get("aliases") or [],
                "core_facts": n.get("core_facts") or [],
                "traits": n.get("traits") or [],
            }
            for n in raw_nodes
        ]
        edges = [
            {
                "source": e.get("source"),
                "target": e.get("target"),
                "predicate": e.get("predicate") or "",
                "predicate_surface": e.get("predicate_surface") or "",
            }
            for e in raw_edges
            if e.get("source") and e.get("target")
        ]
        return {
            "nodes": nodes,
            "edges": edges,
            "communities": communities,
        }

    async def get_entity_subgraph(self, user_id: uuid.UUID, entity_id: str) -> dict:
        """单实体一跳子图。"""
        from app.repositories.neo4j.memory_graph_repository import (
            MemoryGraphRepository,
        )

        raw_nodes, raw_edges = await MemoryGraphRepository().entity_subgraph(
            str(user_id), entity_id
        )
        nodes = [
            {
                "id": n.get("id"),
                "name": n.get("name"),
                "type": n.get("type"),
                "description": n.get("description") or "",
                "community_id": n.get("community_id"),
            }
            for n in raw_nodes
        ]
        edges = [
            {
                "source": e.get("source"),
                "target": e.get("target"),
                "predicate": e.get("predicate") or "",
                "predicate_surface": e.get("predicate_surface") or "",
            }
            for e in raw_edges
            if e.get("source") and e.get("target")
        ]
        return {"center": entity_id, "nodes": nodes, "edges": edges}

    async def get_timeline(self, user_id: uuid.UUID) -> list[dict]:
        """事件时间线（按 event_time 倒序）。"""
        from app.repositories.neo4j.memory_graph_repository import (
            MemoryGraphRepository,
        )

        rows = await MemoryGraphRepository().event_timeline(str(user_id))
        return [
            {
                "id": r.get("id"),
                "title": r.get("title"),
                "description": r.get("description") or "",
                "event_time": r.get("event_time"),
                "created_at": r.get("created_at"),
                "participants": r.get("participants") or [],
            }
            for r in rows
        ]

    @staticmethod
    def to_out_dict(memory: Memory) -> dict:
        return {
            "id": str(memory.id),
            "raw_text": memory.raw_text,
            "source": memory.source,
            "status": memory.status,
            "error_msg": memory.error_msg,
            "graph_stats": memory.graph_stats,
            "created_at": memory.created_at.isoformat() if memory.created_at else None,
        }
