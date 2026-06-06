"""实体去重消歧：规则初筛 + LLM 判定 + 与图谱已有实体的二层融合。

两层去重：
- 第一层（批内）：本次萃取出的实体之间，名称/向量相似的候选对交给 LLM 判定是否同一，
  合并别名与描述，得到去重后实体集 + id 重定向表。
- 第二层（图侧）：去重后实体再与 Neo4j 同类型已有实体比对，命中则复用已有实体 id，
  保证同一实体跨多次萃取只有一个图节点。
"""
import difflib

from app.core.llm.client import LLMClient
from app.core.logging import get_logger
from app.core.memory.extraction.models import DedupDecision
from app.core.memory.graph_models import EntityNode
from app.core.memory.json_utils import parse_json_object
from app.core.memory.prompt_renderer import render_prompt
from app.repositories.neo4j.memory_graph_repository import MemoryGraphRepository

logger = get_logger(__name__)

_NAME_SIM_GATE = 0.80  # 候选对名称相似度门槛
_MERGE_CONFIDENCE = 0.80  # LLM 合并置信度门槛


def _text_sim(a: str, b: str) -> float:
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na > 0 and nb > 0 else 0.0


def _contains(a: str, b: str) -> bool:
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    return bool(a and b and (a in b or b in a))


def _merge_into(canon: EntityNode, other: EntityNode) -> None:
    """把 other 的别名/描述/动力学属性并入 canon（保留方）。"""
    names = set(canon.aliases) | set(other.aliases) | {other.name}
    names.discard(canon.name)
    canon.aliases = [n for n in names if n]
    if len(other.description) > len(canon.description):
        canon.description = other.description
    # 动力学：重要度/置信度取较大、提及次数累加、连接强度合并
    canon.importance = max(canon.importance, other.importance)
    canon.confidence = max(canon.confidence, other.confidence)
    canon.mention_count = canon.mention_count + other.mention_count
    if canon.connect_strength != other.connect_strength:
        canon.connect_strength = "both"


async def _judge_same(
    client: LLMClient, a: EntityNode, b: EntityNode, ctx: dict
) -> DedupDecision:
    prompt = render_prompt(
        "dedup_entity.jinja2",
        entity_a={"name": a.name, "type": a.type, "description": a.description, "aliases": a.aliases},
        entity_b={"name": b.name, "type": b.type, "description": b.description, "aliases": b.aliases},
        ctx=ctx,
    )
    try:
        answer = await client.chat(
            [{"role": "user", "content": prompt}], temperature=0.0, max_tokens=300
        )
        return DedupDecision.model_validate(parse_json_object(answer))
    except Exception as e:
        logger.warning("实体去重判定失败（视为不合并）: %s", e)
        return DedupDecision()


async def dedup_within_batch(
    client: LLMClient, entities: list[EntityNode]
) -> tuple[list[EntityNode], dict[str, str]]:
    """第一层：批内去重。返回（去重后实体, id 重定向表 old_id->canon_id）。"""
    redirect: dict[str, str] = {}
    if len(entities) < 2:
        return entities, redirect

    # 同名同类型直接合并（不必问 LLM）
    by_key: dict[tuple[str, str], EntityNode] = {}
    survivors: list[EntityNode] = []
    for ent in entities:
        key = (ent.name.strip().lower(), ent.type)
        if key in by_key:
            canon = by_key[key]
            _merge_into(canon, ent)
            redirect[ent.id] = canon.id
        else:
            by_key[key] = ent
            survivors.append(ent)

    # 候选对：同类型 + 名称相似/向量相似/包含，交给 LLM 判定
    n = len(survivors)
    for i in range(n):
        a = survivors[i]
        if a.id in redirect:
            continue
        for j in range(i + 1, n):
            b = survivors[j]
            if b.id in redirect or a.type != b.type:
                continue
            txt = _text_sim(a.name, b.name)
            emb = _cosine(a.name_embedding, b.name_embedding)
            con = _contains(a.name, b.name)
            if max(txt, emb) < _NAME_SIM_GATE and not con:
                continue
            ctx = {"name_text_sim": round(txt, 3), "name_embed_sim": round(emb, 3), "name_contains": con}
            decision = await _judge_same(client, a, b, ctx)
            if decision.same_entity and decision.confidence >= _MERGE_CONFIDENCE:
                if decision.canonical_idx == 1:
                    _merge_into(b, a)
                    redirect[a.id] = b.id
                    break  # a 已被并掉，跳出内层
                _merge_into(a, b)
                redirect[b.id] = a.id

    deduped = [e for e in survivors if e.id not in redirect]
    return deduped, redirect


async def merge_with_graph(
    client: LLMClient, repo: MemoryGraphRepository, user_id: str, entities: list[EntityNode]
) -> tuple[list[EntityNode], dict[str, str]]:
    """第二层：与 Neo4j 已有同类型实体融合。

    命中已有实体则把本次实体 id 重定向到已有 id（复用图节点），
    并把新别名/描述补进该实体。返回（待写入实体, id 重定向表 new_id->existing_id）。
    """
    redirect: dict[str, str] = {}
    out: list[EntityNode] = []
    cache: dict[str, list[dict]] = {}  # 按类型缓存已有实体，减少查询

    for ent in entities:
        if ent.type not in cache:
            cache[ent.type] = await repo.list_entities_by_type(user_id, ent.type)
        existing = cache[ent.type]

        # 同名同类型直接复用已有图节点，不问 LLM。
        # 关键：保证「用户」等稳定自指实体跨多次萃取只有一个图节点，
        # 避免 LLM 非确定性判定把同名实体反复判为不同而重复建节点。
        norm_name = ent.name.strip().lower()
        exact = next(
            (r for r in existing if (r.get("name") or "").strip().lower() == norm_name),
            None,
        )
        if exact is not None:
            existing_node = EntityNode(
                id=exact["id"], user_id=user_id, name=exact.get("name", ""),
                type=ent.type, description=exact.get("description") or "",
                aliases=exact.get("aliases") or [], mention_count=0,
            )
            _merge_into(existing_node, ent)
            existing_node.name_embedding = ent.name_embedding or exact.get("name_embedding")
            redirect[ent.id] = existing_node.id
            out.append(existing_node)
            continue

        best = None
        best_score = 0.0
        for row in existing:
            txt = _text_sim(ent.name, row.get("name", ""))
            emb = _cosine(ent.name_embedding, row.get("name_embedding"))
            con = _contains(ent.name, row.get("name", ""))
            score = max(txt, emb)
            if (score >= _NAME_SIM_GATE or con) and score >= best_score:
                best, best_score = row, score

        if best is None:
            out.append(ent)
            continue

        ctx = {
            "name_text_sim": round(best_score, 3),
            "name_embed_sim": round(best_score, 3),
            "name_contains": _contains(ent.name, best.get("name", "")),
        }
        existing_node = EntityNode(
            id=best["id"], user_id=user_id, name=best.get("name", ""),
            type=ent.type, description=best.get("description") or "",
            aliases=best.get("aliases") or [], mention_count=0,
        )
        decision = await _judge_same(client, existing_node, ent, ctx)
        if decision.same_entity and decision.confidence >= _MERGE_CONFIDENCE:
            _merge_into(existing_node, ent)
            existing_node.name_embedding = ent.name_embedding or None
            redirect[ent.id] = existing_node.id
            out.append(existing_node)
        else:
            out.append(ent)

    return out, redirect


__all__ = ["dedup_within_batch", "merge_with_graph"]
