"""标准评测指标函数（纯函数，无副作用）。

检索类：输入「排序后的 id 列表 ranked」+「相关 id 集合 gold」。
集合类：实体/三元组级 P/R/F1。
聚类类：实体去重 Pairwise P/R/F1。

名称匹配：实体/三元组的名字用「归一化 + 包含」口径（name_match），即更完整或更具体的名算命中
（如「日本京都」命中「京都」、「上海徐汇区」命中「徐汇区」），避免 exact-string 对 LLM 合理变体的过苛惩罚；
但通用自指「用户」只精确匹配，防止被「用户的X」泛滥误命中。
"""
import math
import re


def norm_name(s: str) -> str:
    """名称归一化：去首尾空白、去内部空白、小写。"""
    return re.sub(r"\s+", "", (s or "").strip()).lower()


def name_match(a: str, b: str) -> bool:
    """两个实体名是否视为同一个：归一化相等，或一方是另一方的子串（更完整/更具体的名算命中）。

    通用自指「用户」只允许精确匹配——它是几乎所有「用户的X」的子串，放开会大面积误命中。
    """
    na, nb = norm_name(a), norm_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if na == "用户" or nb == "用户":
        return False
    return na in nb or nb in na


def canonicalize(ranked: list, gold: list) -> list:
    """把召回名按 name_match 归一到命中的 gold 名（命中则用 gold 名，否则保留原名），并按序去重。

    便于直接复用基于精确集合的排序指标（Recall@k/MRR/nDCG）。
    """
    out: list = []
    seen: set = set()
    for name in ranked:
        m = next((g for g in gold if name_match(name, g)), None)
        key = m if m is not None else name
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


# ── 检索 ──

def recall_at_k(ranked: list, gold: list, k: int) -> float:
    g = set(gold)
    if not g:
        return 0.0
    return len(set(ranked[:k]) & g) / len(g)


def precision_at_k(ranked: list, gold: list, k: int) -> float:
    if k <= 0:
        return 0.0
    return len(set(ranked[:k]) & set(gold)) / k


def mrr(ranked: list, gold: list) -> float:
    g = set(gold)
    for i, r in enumerate(ranked, 1):
        if r in g:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: list, gold: list, k: int) -> float:
    g = set(gold)
    dcg = sum(1.0 / math.log2(i + 1) for i, r in enumerate(ranked[:k], 1) if r in g)
    ideal = min(len(g), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal + 1))
    return dcg / idcg if idcg > 0 else 0.0


# ── 集合 P/R/F1（抽取）──

def prf1(pred: set, gold: set) -> tuple[float, float, float]:
    if not pred and not gold:
        return 1.0, 1.0, 1.0
    tp = len(pred & gold)
    p = tp / len(pred) if pred else 0.0
    r = tp / len(gold) if gold else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f1


def _fuzzy_prf1(pred: set, gold: set, match) -> tuple[float, float, float]:
    """用自定义 match(p, g) 做的宽松 P/R/F1（双向匹配计数）。"""
    if not pred and not gold:
        return 1.0, 1.0, 1.0
    matched_g = sum(1 for g in gold if any(match(p, g) for p in pred))
    matched_p = sum(1 for p in pred if any(match(p, g) for g in gold))
    r = matched_g / len(gold) if gold else 0.0
    p = matched_p / len(pred) if pred else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f1


def prf1_names(pred: set, gold: set) -> tuple[float, float, float]:
    """实体名集合 P/R/F1，名字用 name_match（归一化 + 包含）口径。"""
    return _fuzzy_prf1(pred, gold, name_match)


def _triple_match(t1: tuple, t2: tuple) -> bool:
    """三元组匹配：主/宾名用 name_match，谓词归一化后精确相等。"""
    return (
        name_match(t1[0], t2[0])
        and norm_name(t1[1]) == norm_name(t2[1])
        and name_match(t1[2], t2[2])
    )


def prf1_triples(pred: set, gold: set) -> tuple[float, float, float]:
    """三元组 (主, 谓, 宾) 集合 P/R/F1，名字用包含口径、谓词精确。"""
    return _fuzzy_prf1(pred, gold, _triple_match)


# ── 聚类 Pairwise P/R/F1（去重）──

def _pairs(clusters: list[list]) -> set:
    s: set = set()
    for c in clusters:
        items = sorted(set(c))
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                s.add((items[i], items[j]))
    return s


def pairwise_prf1(pred_clusters: list[list], gold_clusters: list[list]) -> tuple[float, float, float]:
    return prf1(_pairs(pred_clusters), _pairs(gold_clusters))


def avg(rows: list[float]) -> float:
    return round(sum(rows) / len(rows), 4) if rows else 0.0
