"""记忆萃取编排：把一段来源文本完整处理并写入图谱。

流程：
    分块 → 陈述抽取 → 三元组萃取 → 实体 name 向量化
    → 批内去重 → 与图谱已有实体二层融合 → 组装四层溯源图模型 → 写 Neo4j

四层溯源：Dialogue（来源）→ Chunk（片段）→ Statement（陈述）→ Entity（实体），
实体间挂 RELATION 三元组边。返回写入统计，供上层记录 PG memories 溯源。
"""
from datetime import datetime

from app.core.llm.client import LLMClient
from app.core.logging import get_logger
from app.core.memory.extraction import dedup, embedder, triplet_extractor
from app.core.memory.extraction.models import ExtractedEvent, ExtractedTriplet
from app.core.memory.graph_models import (
    SOURCE_MANUAL,
    ChunkNode,
    DialogueNode,
    EntityNode,
    EventNode,
    InvolvesEdge,
    MentionEdge,
    RelationEdge,
    StatementNode,
)
from app.core.memory.ontology import normalize_entity_type, normalize_predicate
from app.core.memory.preprocessing import chunker, statement_extractor
from app.repositories.neo4j.memory_graph_repository import MemoryGraphRepository

logger = get_logger(__name__)


class ExtractionStats:
    """一次萃取的写入统计与实体 id 列表（供溯源）。"""

    def __init__(self):
        self.dialogue_id: str = ""
        self.chunk_count = 0
        self.statement_count = 0
        self.entity_count = 0
        self.relation_count = 0
        self.event_count = 0
        self.entity_ids: list[str] = []

    def to_dict(self) -> dict:
        return {
            "dialogue_id": self.dialogue_id,
            "chunks": self.chunk_count,
            "statements": self.statement_count,
            "entities": self.entity_count,
            "relations": self.relation_count,
            "events": self.event_count,
            "entity_ids": self.entity_ids,
        }


def _parse_dt(value: str | None) -> datetime | None:
    if not value or str(value).strip().upper() in {"NULL", "NONE", ""}:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


async def run_extraction(
    *,
    chat_client: LLMClient,
    embed_client: LLMClient,
    user_id: str,
    text: str,
    source: str = SOURCE_MANUAL,
    source_message_id: str | None = None,
    dialog_at: datetime | None = None,
) -> ExtractionStats:
    """对一段文本执行完整萃取并写入图谱。"""
    stats = ExtractionStats()
    user_id = str(user_id)
    dialog_at = dialog_at or datetime.now()

    text = (text or "").strip()
    if not text:
        return stats

    # 1. 来源根节点
    dialogue = DialogueNode(
        user_id=user_id, content=text, source=source,
        source_message_id=source_message_id, dialog_at=dialog_at,
    )
    stats.dialogue_id = dialogue.id

    # 2. 分块
    chunk_texts = chunker.split_chunks(text)
    chunks: list[ChunkNode] = [
        ChunkNode(user_id=user_id, dialog_id=dialogue.id, content=ct, sequence=i)
        for i, ct in enumerate(chunk_texts)
    ]
    stats.chunk_count = len(chunks)

    statements: list[StatementNode] = []
    # 收集所有实体（带局部 idx → EntityNode 映射，按 chunk 隔离）与三元组
    entity_pool: list[EntityNode] = []
    mentions: list[MentionEdge] = []
    # 记录 (statement_id, local_idx) → EntityNode，用于三元组连边
    pending_triplets: list[tuple[str, ExtractedTriplet, dict[int, EntityNode]]] = []
    # 收集事件：(ExtractedEvent, 本块实体名→EntityNode 映射)，去重后按参与者连边
    pending_events: list[tuple[ExtractedEvent, dict[str, EntityNode]]] = []

    dialog_at_str = dialog_at.isoformat()

    # 3. 逐块：陈述抽取 → 三元组萃取
    for chunk in chunks:
        extracted_stmts = await statement_extractor.extract_statements(
            chat_client, chunk.content, context=text if len(chunks) > 1 else None
        )
        if not extracted_stmts:
            continue
        triplet_results = await triplet_extractor.extract_triplets_batch(
            chat_client, extracted_stmts, context=chunk.content, dialog_at=dialog_at_str
        )
        # 本块内 实体名 → EntityNode（供事件按 participants 名字关联）
        chunk_name_map: dict[str, EntityNode] = {}
        for stmt, tres in zip(extracted_stmts, triplet_results):
            stmt_node = StatementNode(
                user_id=user_id, chunk_id=chunk.id, statement=stmt.statement,
                stmt_type=stmt.statement_type, temporal_type=stmt.temporal_type,
                dialog_at=dialog_at,
                importance=stmt.importance, confidence=stmt.confidence,
                has_emotional_state=stmt.has_emotional_state,
                emotion_type=stmt.emotion_type,
                emotion_intensity=stmt.emotion_intensity,
                emotion_keywords=stmt.emotion_keywords,
            )
            statements.append(stmt_node)
            # 该陈述内 局部 entity_idx → EntityNode
            idx_map: dict[int, EntityNode] = {}
            for ent in tres.entities:
                node = EntityNode(
                    user_id=user_id, name=ent.name.strip(),
                    type=normalize_entity_type(ent.type),
                    description=ent.description or "",
                    importance=ent.importance, confidence=ent.confidence,
                )
                idx_map[ent.entity_idx] = node
                entity_pool.append(node)
                chunk_name_map[node.name] = node
                mentions.append(MentionEdge(
                    user_id=user_id, statement_id=stmt_node.id, entity_id=node.id
                ))
            for trip in tres.triplets:
                pending_triplets.append((stmt_node.id, trip, idx_map))
            for ev in tres.events:
                pending_events.append((ev, chunk_name_map))

    stats.statement_count = len(statements)
    if not entity_pool:
        # 没抽到实体也写来源 + 陈述（保留溯源），关系/事件为空
        await _persist(
            dialogue=dialogue, chunks=chunks, statements=statements,
            entities=[], mentions=mentions, relations=[], events=[], involves=[],
        )
        return stats

    # 4. 实体 name 向量化
    vectors = await embedder.embed_texts(embed_client, [e.name for e in entity_pool])
    for ent, vec in zip(entity_pool, vectors):
        ent.name_embedding = vec

    # 5. 批内去重 → id 重定向
    deduped, redirect1 = await dedup.dedup_within_batch(chat_client, entity_pool)
    # 6. 与图谱已有实体二层融合
    repo = MemoryGraphRepository()
    final_entities, redirect2 = await dedup.merge_with_graph(
        chat_client, repo, user_id, deduped
    )

    # 合并两层重定向：原始 EntityNode.id → 最终落库 id
    def resolve(eid: str) -> str:
        eid = redirect1.get(eid, eid)
        eid = redirect2.get(eid, eid)
        return eid

    final_by_id = {e.id: e for e in final_entities}
    stats.entity_count = len(final_entities)
    stats.entity_ids = list(final_by_id.keys())

    # 7. mention 边重定向到最终实体 id
    for m in mentions:
        m.entity_id = resolve(m.entity_id)
    # 去掉指向不存在实体的 mention（被合并的已重定向，正常都存在）
    mentions = [m for m in mentions if m.entity_id in final_by_id]

    # 8. 三元组 → RELATION 边
    relations: list[RelationEdge] = []
    for stmt_id, trip, idx_map in pending_triplets:
        subj = idx_map.get(trip.subject_id)
        obj = idx_map.get(trip.object_id)
        if not subj or not obj:
            continue
        sid = resolve(subj.id)
        oid = resolve(obj.id)
        if sid not in final_by_id or oid not in final_by_id or sid == oid:
            continue
        relations.append(RelationEdge(
            user_id=user_id, source_id=sid, target_id=oid,
            predicate=normalize_predicate(trip.predicate),
            predicate_surface=trip.predicate_surface or "",
            source_text="", statement_id=stmt_id, value=trip.value,
            valid_at=_parse_dt(trip.valid_at), invalid_at=_parse_dt(trip.invalid_at),
            importance=trip.importance, confidence=trip.confidence,
        ))
    stats.relation_count = len(relations)

    # 9. 事件 → Event 节点 + INVOLVES 边（按 participants 名字匹配到最终实体）
    events: list[EventNode] = []
    involves: list[InvolvesEdge] = []
    for ev, name_map in pending_events:
        title = (ev.title or "").strip()
        if not title:
            continue
        event_node = EventNode(
            user_id=user_id, title=title,
            description=ev.description or "",
            event_time=_parse_dt(ev.event_time),
        )
        # 参与者名字 → 本块 EntityNode → 重定向到最终实体 id
        linked: set[str] = set()
        for pname in ev.participants:
            ent = name_map.get((pname or "").strip())
            if not ent:
                continue
            eid = resolve(ent.id)
            if eid in final_by_id and eid not in linked:
                linked.add(eid)
                involves.append(InvolvesEdge(
                    user_id=user_id, event_id=event_node.id, entity_id=eid
                ))
        events.append(event_node)
    stats.event_count = len(events)

    # 10. 写图（单事务原子落库）
    await _persist(
        dialogue=dialogue, chunks=chunks, statements=statements,
        entities=final_entities, mentions=mentions, relations=relations,
        events=events, involves=involves,
    )

    # 11. 增量社区聚类（新实体归入社区；失败不影响萃取结果）
    try:
        from app.core.memory.clustering.label_propagation import LabelPropagationEngine

        engine = LabelPropagationEngine(chat_client=chat_client)
        await engine.run(user_id, new_entity_ids=stats.entity_ids)
    except Exception as e:
        logger.warning("增量社区聚类失败（忽略）: %s", e)

    logger.info("记忆萃取完成: %s", stats.to_dict())
    return stats


async def _persist(
    *,
    dialogue: DialogueNode,
    chunks: list[ChunkNode],
    statements: list[StatementNode],
    entities: list[EntityNode],
    mentions: list[MentionEdge],
    relations: list[RelationEdge],
    events: list[EventNode],
    involves: list[InvolvesEdge],
) -> None:
    repo = MemoryGraphRepository()
    await repo.save_graph(
        dialogues=[dialogue], chunks=chunks, statements=statements,
        entities=entities, events=events, mentions=mentions,
        relations=relations, involves=involves,
    )


__all__ = ["run_extraction", "ExtractionStats"]
