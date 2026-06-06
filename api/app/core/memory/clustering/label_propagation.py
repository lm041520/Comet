"""标签传播聚类引擎（LPA）。

对 Neo4j 中某用户的 Entity 节点做社区聚类：
- 全量初始化：所有实体初始各自一个标签，按邻居加权投票迭代传播至收敛
- 增量更新：新实体按邻居投票归入已有社区或新建

加权投票权重 = 语义相似度(name_embedding 余弦) * 0.6 + 关系连接强度 * 0.4。
迭代收敛后做社区合并（平均向量余弦 > 阈值），再为每个社区用 LLM 生成名称+摘要。
"""
import uuid
from math import sqrt

from app.core.llm.client import LLMClient
from app.core.logging import get_logger
from app.repositories.neo4j.community_repository import CommunityRepository

logger = get_logger(__name__)

MAX_ITERATIONS = 10
MERGE_THRESHOLD = 0.85
_SEM_WEIGHT = 0.6
_REL_WEIGHT = 0.4


def _cosine(v1: list[float] | None, v2: list[float] | None) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    n1 = sqrt(sum(a * a for a in v1))
    n2 = sqrt(sum(b * b for b in v2))
    return dot / (n1 * n2) if n1 and n2 else 0.0


def _weighted_vote(
    neighbors: list[dict], self_emb: list[float] | None, labels: dict[str, str]
) -> str | None:
    """邻居按 语义相似度*0.6 + 关系连接*0.4 加权投票，返回得票最高的社区标签。"""
    votes: dict[str, float] = {}
    for nb in neighbors:
        cid = labels.get(nb["id"], nb.get("community_id"))
        if not cid:
            continue
        sem = _cosine(self_emb, nb.get("name_embedding"))
        weight = _SEM_WEIGHT * sem + _REL_WEIGHT * 1.0  # 有关系边即记一次连接强度
        votes[cid] = votes.get(cid, 0.0) + weight
    return max(votes, key=votes.__getitem__) if votes else None


class LabelPropagationEngine:
    """标签传播聚类引擎。"""

    def __init__(self, chat_client: LLMClient | None = None):
        self.repo = CommunityRepository()
        self.chat_client = chat_client  # 可选，用于生成社区名/摘要

    async def run(self, user_id: str, new_entity_ids: list[str] | None = None) -> None:
        """统一入口：无社区→全量；有社区且给了新实体→增量。"""
        if not await self.repo.has_communities(user_id):
            await self.full_clustering(user_id)
        elif new_entity_ids:
            await self.incremental_update(user_id, new_entity_ids)

    async def full_clustering(self, user_id: str) -> None:
        entities = await self.repo.list_entities_with_embedding(user_id)
        if not entities:
            return
        ids = [e["id"] for e in entities]
        emb_map = {e["id"]: e.get("name_embedding") for e in entities}
        labels = {eid: eid for eid in ids}  # 初始各自一个标签

        neighbors_cache = await self.repo.neighbors_for_vote(user_id, ids)

        for _ in range(MAX_ITERATIONS):
            changed = 0
            for eid in ids:
                nbs = neighbors_cache.get(eid, [])
                new_label = _weighted_vote(nbs, emb_map.get(eid), labels)
                if new_label and new_label != labels[eid]:
                    labels[eid] = new_label
                    changed += 1
            if changed == 0:
                break

        # 写标签 → 社区节点 + 归属
        await self._flush_labels(user_id, labels)
        # 合并相似社区
        community_ids = list(set(labels.values()))
        community_ids = await self._merge_communities(user_id, community_ids)
        await self.repo.prune_empty(user_id)
        # 生成元数据
        await self._generate_metadata(user_id, community_ids)
        logger.info("全量聚类完成: user=%s 社区数=%d", user_id, len(community_ids))

    async def incremental_update(self, user_id: str, new_entity_ids: list[str]) -> None:
        emb_rows = await self.repo.list_entities_with_embedding(user_id)
        emb_map = {e["id"]: e.get("name_embedding") for e in emb_rows}
        neighbors_cache = await self.repo.neighbors_for_vote(user_id, new_entity_ids)
        touched: set[str] = set()
        for eid in new_entity_ids:
            nbs = neighbors_cache.get(eid, [])
            target = _weighted_vote(nbs, emb_map.get(eid), {})
            if target is None:
                target = self._new_id()
                await self.repo.upsert_community(user_id, target)
            await self.repo.assign_entity(user_id, eid, target)
            await self.repo.refresh_member_count(user_id, target)
            touched.add(target)
        await self._generate_metadata(user_id, list(touched))
        logger.info("增量聚类完成: user=%s 新实体=%d", user_id, len(new_entity_ids))

    async def _flush_labels(self, user_id: str, labels: dict[str, str]) -> None:
        for cid in set(labels.values()):
            await self.repo.upsert_community(user_id, cid)
        for eid, cid in labels.items():
            await self.repo.assign_entity(user_id, eid, cid)
        for cid in set(labels.values()):
            await self.repo.refresh_member_count(user_id, cid)

    async def _merge_communities(
        self, user_id: str, community_ids: list[str]
    ) -> list[str]:
        """平均向量余弦 > 阈值的社区合并，保留成员多的一方。返回存活社区 id。"""
        avg_emb: dict[str, list[float] | None] = {}
        sizes: dict[str, int] = {}
        for cid in community_ids:
            members = await self.repo.get_members(user_id, cid)
            sizes[cid] = len(members)
            embs = [m["name_embedding"] for m in members if m.get("name_embedding")]
            if embs:
                dim = len(embs[0])
                avg_emb[cid] = [sum(e[i] for e in embs) / len(embs) for i in range(dim)]
            else:
                avg_emb[cid] = None

        merged_into: dict[str, str] = {}

        def root(x: str) -> str:
            while x in merged_into:
                x = merged_into[x]
            return x

        for i in range(len(community_ids)):
            for j in range(i + 1, len(community_ids)):
                r1, r2 = root(community_ids[i]), root(community_ids[j])
                if r1 == r2:
                    continue
                if _cosine(avg_emb.get(r1), avg_emb.get(r2)) <= MERGE_THRESHOLD:
                    continue
                keep, dissolve = (r1, r2) if sizes.get(r1, 0) >= sizes.get(r2, 0) else (r2, r1)
                merged_into[dissolve] = keep
                for m in await self.repo.get_members(user_id, dissolve):
                    await self.repo.assign_entity(user_id, m["id"], keep)
                sizes[keep] = sizes.get(keep, 0) + sizes.get(dissolve, 0)
                sizes[dissolve] = 0
                await self.repo.refresh_member_count(user_id, keep)
                await self.repo.refresh_member_count(user_id, dissolve)

        return [cid for cid in community_ids if cid not in merged_into]

    async def _generate_metadata(self, user_id: str, community_ids: list[str]) -> None:
        """为社区生成名称+摘要。有 chat 模型走 LLM，否则成员名拼接兜底。"""
        for cid in community_ids:
            members = await self.repo.get_members(user_id, cid)
            if not members:
                continue
            names = [m["name"] for m in members if m.get("name")]
            name = "、".join(names[:3]) if names else "未命名社区"
            summary = f"包含实体：{', '.join(names[:10])}"
            if self.chat_client and names:
                name, summary = await self._llm_meta(cid, members)
            await self.repo.update_metadata(user_id, cid, name, summary)

    async def _llm_meta(self, cid: str, members: list[dict]) -> tuple[str, str]:
        entity_lines = []
        for m in members[:20]:
            desc = f"：{m['description']}" if m.get("description") else ""
            entity_lines.append(f"- {m.get('name', '')}{desc}")
        prompt = (
            "以下是一组语义相关的记忆实体：\n"
            + "\n".join(entity_lines)
            + "\n\n请为这组实体代表的主题：\n"
            "1. 起一个简洁中文名称（不超过10字）\n"
            "2. 写一句话摘要（不超过60字）\n\n"
            "严格按以下格式输出：\n名称：<名称>\n摘要：<摘要>"
        )
        try:
            text = await self.chat_client.chat(
                [{"role": "user", "content": prompt}], temperature=0.4, max_tokens=200
            )
            name, summary = "", ""
            for line in text.strip().splitlines():
                if line.startswith("名称："):
                    name = line[3:].strip()
                elif line.startswith("摘要："):
                    summary = line[3:].strip()
            names = [m.get("name", "") for m in members if m.get("name")]
            return (
                name or ("、".join(names[:3]) if names else "未命名社区"),
                summary or f"包含实体：{', '.join(names[:10])}",
            )
        except Exception as e:
            logger.warning("社区元数据 LLM 生成失败（兜底）: %r", e)
            names = [m.get("name", "") for m in members if m.get("name")]
            return "、".join(names[:3]) or "未命名社区", f"包含实体：{', '.join(names[:10])}"

    @staticmethod
    def _new_id() -> str:
        return uuid.uuid4().hex


__all__ = ["LabelPropagationEngine"]
