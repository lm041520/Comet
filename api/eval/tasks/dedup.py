"""实体去重评测：Pairwise Precision / Recall / F1。

对每组 mentions 构造 EntityNode（同类型 + 向量化名称），跑批内去重 dedup_within_batch，
按重定向表把 mentions 归并成预测聚类，与 gold 聚类做 pairwise 比对。
明细记录预测聚类 vs gold，便于看「该合没合 / 错合」并调相似度门槛或 prompt。
"""
import json
from pathlib import Path

from app.core.memory.extraction.dedup import dedup_within_batch
from app.core.memory.graph_models import EntityNode
from eval import metrics
from eval.eval_config import EVAL_USER_ID

_GOLD = Path(__file__).parent.parent / "fixtures" / "gold" / "dedup.json"
_TYPE = "其他"  # 评测里所有 mention 设同一类型，确保互为去重候选


def _resolve(eid: str, redirect: dict) -> str:
    seen = set()
    while eid in redirect and eid not in seen:
        seen.add(eid)
        eid = redirect[eid]
    return eid


async def _predict_clusters(chat_client, embed_client, mentions: list[str]) -> list[list[str]]:
    entities = [EntityNode(user_id=str(EVAL_USER_ID), name=m, type=_TYPE) for m in mentions]
    vectors = await embed_client.embed(mentions)
    for ent, vec in zip(entities, vectors):
        ent.name_embedding = vec
    _, redirect = await dedup_within_batch(chat_client, entities)
    id_to_name = {e.id: e.name for e in entities}
    clusters: dict[str, list[str]] = {}
    for e in entities:
        canon = _resolve(e.id, redirect)
        clusters.setdefault(canon, []).append(id_to_name[e.id] if canon == e.id else e.name)
    # 用名称组装聚类
    out: list[list[str]] = []
    for canon, _names in clusters.items():
        members = [e.name for e in entities if _resolve(e.id, redirect) == canon]
        out.append(members)
    return out


async def eval_dedup(chat_client, embed_client) -> tuple[dict, list]:
    data = json.loads(_GOLD.read_text(encoding="utf-8"))
    scores: list[tuple[float, float, float]] = []
    details: list[dict] = []
    total = len(data)
    for i, item in enumerate(data, 1):
        mentions = item["mentions"]
        gold = item["gold_clusters"]
        print(f"    [去重] {i}/{total} {len(mentions)} 个 mention…")
        pred = await _predict_clusters(chat_client, embed_client, mentions)
        p, r, f = metrics.pairwise_prf1(pred, gold)
        scores.append((p, r, f))
        details.append({
            "mentions": mentions,
            "gold_clusters": gold,
            "pred_clusters": pred,
            "pairwise": {"P": round(p, 4), "R": round(r, 4), "F1": round(f, 4)},
        })
    table = {"Pairwise": {
        "Precision": metrics.avg([s[0] for s in scores]),
        "Recall": metrics.avg([s[1] for s in scores]),
        "F1": metrics.avg([s[2] for s in scores]),
    }}
    return table, details
