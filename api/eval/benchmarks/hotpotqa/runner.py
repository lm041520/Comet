"""HotpotQA distractor runner：检索 top-k 段落 → 多跳 chat 答 → EM/F1 + 检索 Recall。

设计要点：
- 每题独立 user_id（uuid5(qid)），灌入 → 查 → 清理；不互相干扰、可重入。
- 段落级粒度（source_id = title），便于按 `gold_titles` 算检索 Recall。
- 三组对照：无 Verifier(A) / 同模型 self-critique(B) / 跨模型 Verifier(C) —— ② Verifier Loop 完成后才接入。
  当前先支持 baseline（无 Verifier），保留接口供 ② 接入后扩展。
- 答案评估走 HotpotQA 官方 `exact_match_score` / `f1_score` 口径（normalize + token 级 P/R/F1）。
"""
from __future__ import annotations

import asyncio
import re
import string
import uuid
from collections import Counter
from typing import Any

from app.core.rag.indexing import (
    CHUNKS_INDEX,
    CHUNK_TYPE_CHILD,
    build_chunk_doc,
    bulk_index,
    ensure_index,
)
from app.db.elastic import get_es

from eval import clients
from eval import metrics as M
from eval.benchmarks._common import write_benchmark_details, write_benchmark_report
from eval.benchmarks.hotpotqa.loader import load
from eval.benchmarks.hotpotqa.qa_verifier import judge_qa

K_RETRIEVE = 4  # 每题检索 top-4 段落给 chat 答（distractor 共 10 段，2 段是 gold）

# 命名空间根：每题 user_id = uuid5(NS_HOTPOT, qid)
_NS_HOTPOT = uuid.UUID("eee30000-0000-0000-0000-0000000000c3")


def _qid_to_uid(qid: str) -> str:
    return str(uuid.uuid5(_NS_HOTPOT, qid))


# ── HotpotQA 官方 EM/F1 评测口径（normalize + token） ──

def _normalize_answer(s: str) -> str:
    """官方口径：删除冠词、标点、多余空白、转小写。"""
    s = s.lower()
    s = re.sub(r"\b(a|an|the)\b", " ", s)
    s = "".join(ch for ch in s if ch not in set(string.punctuation))
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _em(pred: str, gold: str) -> float:
    return float(_normalize_answer(pred) == _normalize_answer(gold))


def _f1(pred: str, gold: str) -> float:
    pt = _normalize_answer(pred).split()
    gt = _normalize_answer(gold).split()
    if not pt or not gt:
        return float(pt == gt)
    common = Counter(pt) & Counter(gt)
    num_same = sum(common.values())
    if num_same == 0:
        return 0.0
    p = num_same / len(pt)
    r = num_same / len(gt)
    return 2 * p * r / (p + r)


# ── 灌入与检索 ──

async def _ingest_one(embed_client, qid: str, paragraphs: list[dict]) -> None:
    """把单题的 10 段灌进 ES（child 粒度即可，段落本身就短）。"""
    uid = _qid_to_uid(qid)
    es_docs: list[dict] = []
    # 批量算向量
    texts = []
    titles = []
    for p in paragraphs:
        content = " ".join(p["sentences"])
        texts.append(content)
        titles.append(p["title"])
    vectors = await embed_client.embed(texts) if texts else []
    for title, content, vec in zip(titles, texts, vectors):
        es_docs.append(build_chunk_doc(
            user_id=uid, source_type="document", source_id=title,
            doc_name=title, chunk_type=CHUNK_TYPE_CHILD,
            content=content, vector=vec,
        ))
    if es_docs:
        await bulk_index(es_docs)


async def _clear_one(qid: str) -> None:
    es = get_es()
    try:
        await es.delete_by_query(
            index=CHUNKS_INDEX,
            body={"query": {"term": {"user_id": _qid_to_uid(qid)}}},
            refresh=True,
            conflicts="proceed",
        )
    except Exception:  # noqa: BLE001
        pass


# ── chat 回答 ──

_ANSWER_PROMPT = """You are answering a multi-hop question using ONLY the provided paragraphs.

Question: {question}

Paragraphs:
{paragraphs}

Rules:
- Reason briefly and then output the final answer.
- Format: The VERY LAST line of your reply MUST be exactly `ANSWER: <短答案>`
  - `<短答案>` is a short phrase (a name / number / date) or `yes`/`no`.
  - Match the wording in the paragraphs exactly when applicable.
  - No quotation marks, no trailing punctuation, no explanation after `ANSWER:`.
- If the paragraphs do not support a confident answer, still output your best guess on that last line.

Begin."""


_ANSWER_RE_MARKERS = ("ANSWER:", "Answer:", "answer:", "答案:", "Final Answer:", "final answer:")


def _extract_answer(text: str) -> str:
    """从 chat 回复里抽出最终答案。处理推理模型(<think>...</think> + 答案)与普通模型两种输出。

    优先级:
    1. 找最后一个 ANSWER: / 答案: 等 marker,取其后到行尾的字符串
    2. 兜底:取最后一个非空行
    """
    if not text:
        return ""
    # 去除常见 <think>...</think>(reasoning model 输出)
    cleaned = text
    if "</think>" in cleaned:
        cleaned = cleaned.rsplit("</think>", 1)[1]
    cleaned = cleaned.strip()
    if not cleaned:
        cleaned = text.strip()

    # 找最后一个 marker(rfind),取其后到行末
    best: str | None = None
    for marker in _ANSWER_RE_MARKERS:
        idx = cleaned.rfind(marker)
        if idx >= 0:
            tail = cleaned[idx + len(marker):]
            # 取 marker 后第一行非空
            for line in tail.splitlines():
                line = line.strip()
                if line:
                    best = line
                    break
            if best:
                break

    if not best:
        # 兜底:取最后一个非空行
        for line in reversed(cleaned.splitlines()):
            s = line.strip()
            if s:
                best = s
                break

    if not best:
        return ""
    return best.strip(string.punctuation + " \"'")


async def _answer(chat_client, question: str, paragraphs: list[tuple[str, str]]) -> str:
    """让 chat 模型基于检索到的 paragraphs 答 HotpotQA。返回最终答案文本。

    max_tokens 调到 1024:推理模型(deepseek-r1 / -v4-pro 等)思考块通常 200~800 token,
    给少了 thinking 没结束就被截断 → 最终答案丢失。
    """
    p_text = "\n\n".join(f"[{title}]\n{content}" for title, content in paragraphs)
    prompt = _ANSWER_PROMPT.format(question=question, paragraphs=p_text)
    text = await chat_client.chat(
        [{"role": "user", "content": prompt}],
        max_tokens=1024, temperature=0.0,
    )
    return _extract_answer(text)


# ── 主流程 ──

async def run_benchmark(
    embed_client, chat_client, rerank_client=None, *,
    sample: int = 500,
    verifier: str = "none",
    seed: int = 42,
    verifier_client_factory=None,
) -> tuple[dict, list]:
    """跑 HotpotQA distractor + 可选的 Verifier A/B 实验。

    Args:
        embed_client / chat_client / rerank_client: 由 run_eval 注入
        sample: 采样数（按 bridge/comparison 分层）
        verifier: none | same | cross
            - none:  仅算 EM/F1 + 检索 Recall(baseline)
            - same:  答完后用 chat_client 同款做 LLM-as-judge,判 verifier_pass=1/0
            - cross: 答完后用单独配置的 verifier 模型判;未配置降级到 same
        seed: 采样种子
        verifier_client_factory: 可调用 → 返回 cross 模式用的 LLMClient(由 run_eval 注入,
                                  这样 runner 不直接耦合 eval_config 模块)
    """
    # 准备 verifier client(仅 same/cross 用到)
    judge_client = None
    judge_kind_actual = "none"
    if verifier == "same":
        judge_client = chat_client
        judge_kind_actual = "same"
    elif verifier == "cross":
        if verifier_client_factory is not None:
            cross_client = verifier_client_factory()
        else:
            cross_client = None
        if cross_client is None:
            print("[hotpotqa] --verifier=cross 但未配置 EVAL_VERIFIER_*,降级到 same")
            judge_client = chat_client
            judge_kind_actual = "same(降级自 cross)"
        else:
            judge_client = cross_client
            judge_kind_actual = f"cross ({cross_client.model_name})"

    print(f"[hotpotqa] 加载数据集（采样 {sample} 条）… verifier={verifier} (实际: {judge_kind_actual})")
    queries = load(n=sample, seed=seed)
    print(f"  实际采样: {len(queries)} 条（bridge/comparison 按比例）")

    await ensure_index()

    # 累积指标
    em_list: list[float] = []
    f1_list: list[float] = []
    retr_recall_list: list[float] = []  # 检索 top-k 段落对 gold_titles 的覆盖
    verifier_pass_list: list[int] = []  # verifier 判过=1 / 判不过=0(仅 same/cross 收集)
    details: list[dict] = []

    total = len(queries)
    for i, q in enumerate(queries, 1):
        qid = q["qid"]
        uid = _qid_to_uid(qid)
        print(f"  [hotpotqa] {i}/{total}  qid={qid}  type={q['qtype']}")
        print(f"    Q: {q['question'][:80]}")
        # 1. 灌入本题 10 段
        await _ingest_one(embed_client, qid, q["paragraphs"])
        await asyncio.sleep(0.05)  # 给 ES 一点索引时间
        try:
            # 2. 检索 top-k
            rh = await clients.retrieve_hybrid(embed_client, uid, q["question"], 10)
            if rerank_client is not None and len(rh) > K_RETRIEVE:
                rh = await clients.rerank_sources(rerank_client, uid, q["question"], rh, K_RETRIEVE)
            else:
                rh = rh[:K_RETRIEVE]
            # 3. 收集检索到的段落（按 source_id == title 对回 paragraphs）
            title_to_content = {p["title"]: " ".join(p["sentences"]) for p in q["paragraphs"]}
            retrieved = [(t, title_to_content.get(t, "")) for t in rh if t in title_to_content]
            # 4. 评检索 Recall: top-k 中命中 gold_titles 的数量 / 总 gold
            gold = q["gold_titles"]
            hits_in_topk = [t for t in rh if t in gold]
            retr_recall = len(hits_in_topk) / max(1, len(gold))
            retr_recall_list.append(retr_recall)
            print(f"    ✓ 检索 top-{K_RETRIEVE}: {rh} | 命中 gold={hits_in_topk} (Recall={retr_recall:.2f})")
            # 5. 让 chat 答
            pred = await _answer(chat_client, q["question"], retrieved)
            em = _em(pred, q["answer"])
            f1 = _f1(pred, q["answer"])
            em_list.append(em)
            f1_list.append(f1)
            mark = "✓" if em else ("~" if f1 > 0 else "✗")
            print(f"    {mark} pred='{pred[:60]}' | gold='{q['answer'][:60]}' | EM={em:.0f} F1={f1:.2f}")
            # 6. (可选) Verifier 判合格:same/cross 模式
            verifier_pass = None
            if judge_client is not None:
                verifier_pass = await judge_qa(
                    judge_client,
                    question=q["question"],
                    pred=pred,
                    retrieved_passages=retrieved,
                )
                verifier_pass_list.append(verifier_pass)
                # 漏检 = verifier 判过但实际错(em=0)
                leak = int(verifier_pass == 1 and em == 0)
                print(f"    [verifier] pass={verifier_pass} leak={leak}")
            details.append({
                "qid": qid,
                "question": q["question"],
                "type": q["qtype"],
                "gold_answer": q["answer"],
                "gold_titles": gold,
                "retrieved_topk_titles": rh,
                "retrieval_recall": round(retr_recall, 4),
                "pred": pred,
                "em": em,
                "f1": round(f1, 4),
                "verifier_pass": verifier_pass,
            })
        finally:
            await _clear_one(qid)

    # 基础指标
    base_row: dict[str, Any] = {
        "EM(严格正确率)": M.avg(em_list),
        "F1(软正确率)": M.avg(f1_list),
        f"Retr Recall@{K_RETRIEVE}": M.avg(retr_recall_list),
        "样本数": len(em_list),
    }
    # 若开启了 verifier(same/cross),追加 verifier 相关指标
    if verifier_pass_list:
        n_total = len(verifier_pass_list)
        n_pass = sum(verifier_pass_list)
        # 漏检率 = (verifier 判过 ∩ 实际 EM=0) / verifier 判过总数
        leak = sum(
            1 for vp, em in zip(verifier_pass_list, em_list) if vp == 1 and em == 0
        )
        leak_rate = leak / n_pass if n_pass else 0.0
        # verifier 与 EM 一致率 = (二者同时为 1 或同时为 0) / total
        agree = sum(1 for vp, em in zip(verifier_pass_list, em_list) if vp == int(em))
        agree_rate = agree / n_total if n_total else 0.0
        base_row.update({
            "Verifier 判过率": round(n_pass / n_total, 4) if n_total else 0.0,
            "漏检率(judge 通过但 EM=0)": round(leak_rate, 4),
            "与 EM 一致率": round(agree_rate, 4),
        })

    table: dict[str, dict[str, Any]] = {
        f"verifier={verifier}": base_row,
    }

    meta = {
        "数据集": "hotpot_qa / distractor",
        "切分": "validation",
        "采样数": sample,
        "类型分布": _type_distribution(queries),
        "embedding 模型": embed_client.model_name,
        "chat 模型": chat_client.model_name,
        "rerank 模型": rerank_client.model_name if rerank_client else "(未配置)",
        "verifier 配置": verifier,
        "verifier 实际生效": judge_kind_actual,
    }
    notes = [
        "HotpotQA distractor 评测:每题给 10 段(2 gold + 8 distractor),系统先检索 top-k 再多跳答。",
        "**污染声明**:dev 集发布于 2018 年,目前主流 LLM 训练集大概率覆盖;本评测仅用于系统设计对比"
        "(检索/Verifier 配置间),不作绝对水平断言。",
        "**EM(严格正确率)**:答案归一化后完全一致(忽略大小写/标点/the&a&an),0/1 平均即「严格答对率」。",
        "**F1(软正确率)**:token 级 precision/recall 调和平均,反映「答对了但措辞略差」(如 "
        "答 `Anomalisa (2015 film)` vs gold `Anomalisa` → F1≈0.5)。业界两个一起报。",
        "verifier 字段说明:none = 无 Verifier baseline;same = 同 chat 模型 self-critique;"
        "cross = 跨 family verifier 模型(由 EVAL_VERIFIER_* 配置)。",
        "**漏检率**:Verifier 判过但实际 EM=0 的占比 —— 越低代表 Verifier 越可信。"
        "对比 same vs cross 的漏检率即「为什么不能 self-critique」的硬数据。",
    ]
    report = write_benchmark_report(
        "hotpotqa", "HotpotQA distractor (L3)",
        table, meta=meta, extra_notes=notes,
        category="rag",
    )
    detail_path = write_benchmark_details("hotpotqa", details, category="rag")
    print(f"  报告: {report}\n  明细: {detail_path}")
    return table, details


def _type_distribution(queries: list[dict]) -> str:
    c = Counter(q["qtype"] for q in queries)
    return ", ".join(f"{k}={v}" for k, v in c.most_common())
