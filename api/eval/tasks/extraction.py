"""三元组抽取评测：实体级 + 三元组级 Precision / Recall / F1。

对每段 gold 对话跑真实抽取链路（陈述抽取 → 三元组抽取），收集预测的实体名与三元组，
与 gold 比对（集合 P/R/F1）。三元组按 (主语, 归一化谓词, 宾语) 比对，谓词用受控词表归一化
以对齐 gold 的标准谓词。明细记录每段「漏抽 / 多抽」了什么，供调 prompt。
"""
import json
from pathlib import Path

from app.core.memory.extraction.triplet_extractor import extract_triplets_batch
from app.core.memory.ontology import normalize_predicate
from app.core.memory.preprocessing.statement_extractor import extract_statements
from eval import metrics

_GOLD = Path(__file__).parent.parent / "fixtures" / "gold" / "extraction.json"


async def _predict(chat_client, dialogue: str) -> tuple[set, set]:
    """跑抽取链路，返回 (预测实体名集合, 预测三元组集合)。"""
    statements = await extract_statements(chat_client, dialogue)
    entities: set[str] = set()
    triples: set[tuple] = set()
    if statements:
        results = await extract_triplets_batch(chat_client, statements, context=dialogue)
        for tres in results:
            for e in tres.entities:
                entities.add(e.name.strip())
            for t in tres.triplets:
                triples.add((
                    t.subject_name.strip(),
                    normalize_predicate(t.predicate),
                    t.object_name.strip(),
                ))
    return entities, triples


def _gold_triples(rows: list) -> set:
    return {(s.strip(), normalize_predicate(p), o.strip()) for s, p, o in rows}


async def eval_extraction(chat_client) -> tuple[dict, list]:
    data = json.loads(_GOLD.read_text(encoding="utf-8"))
    ent_scores: list[tuple[float, float, float]] = []
    tri_scores: list[tuple[float, float, float]] = []
    details: list[dict] = []
    total = len(data)
    for i, item in enumerate(data, 1):
        print(f"    [抽取] {i}/{total} {item['dialogue'][:24]}…")
        gold_ent = {e.strip() for e in item.get("gold_entities", [])}
        gold_tri = _gold_triples(item.get("gold_triples", []))
        pred_ent, pred_tri = await _predict(chat_client, item["dialogue"])
        ep, er, ef = metrics.prf1_names(pred_ent, gold_ent)
        tp, tr, tf = metrics.prf1_triples(pred_tri, gold_tri)
        ent_scores.append((ep, er, ef))
        tri_scores.append((tp, tr, tf))
        details.append({
            "dialogue": item["dialogue"],
            "gold_entities": sorted(gold_ent),
            "pred_entities": sorted(pred_ent),
            "entity_missed": sorted(gold_ent - pred_ent),
            "entity_extra": sorted(pred_ent - gold_ent),
            "gold_triples": ["|".join(t) for t in sorted(gold_tri)],
            "pred_triples": ["|".join(t) for t in sorted(pred_tri)],
            "triple_missed": ["|".join(t) for t in sorted(gold_tri - pred_tri)],
            "triple_extra": ["|".join(t) for t in sorted(pred_tri - gold_tri)],
        })

    def _avg3(rows):
        return {
            "Precision": metrics.avg([r[0] for r in rows]),
            "Recall": metrics.avg([r[1] for r in rows]),
            "F1": metrics.avg([r[2] for r in rows]),
        }

    table = {"实体级": _avg3(ent_scores), "三元组级": _avg3(tri_scores)}
    return table, details
