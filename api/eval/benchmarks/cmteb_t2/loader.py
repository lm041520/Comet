"""C-MTEB T2Retrieval 数据加载（HuggingFace datasets）。

数据集结构（mteb 风格）：
- corpus:  {_id, title, text}    —— 文档集合
- queries: {_id, text}           —— 查询集合
- qrels:   {query-id, corpus-id, score}  —— 相关性标注（dev/test 切分）

我们用 dev 切分（约 2k 量级，跑得动）。首次下载会缓存到 `api/eval/cache/`。
"""
from __future__ import annotations

from typing import TypedDict

from eval.benchmarks._common import cache_path

# HuggingFace 上的数据集 id(MMTEB 统一迁移到 `mteb/` 组织下,旧路径 `C-MTEB/T2Retrieval`
# 只剩 default config,新路径保留完整三 subset 结构 corpus/queries/default)
_HF_REPO = "mteb/T2Retrieval"


class CMTEBQuery(TypedDict):
    qid: str
    text: str
    relevant_doc_ids: list[str]


class CMTEBCorpusItem(TypedDict):
    cid: str
    title: str
    text: str


class CMTEBData(TypedDict):
    corpus: list[CMTEBCorpusItem]
    queries: list[CMTEBQuery]
    split: str


def load(split: str = "dev", corpus_limit: int | None = None,
         query_limit: int | None = None) -> CMTEBData:
    """加载 T2Retrieval 数据。corpus_limit / query_limit 用于本地小规模快速验证。

    返回:
        corpus:  [{cid, title, text}, ...]
        queries: [{qid, text, relevant_doc_ids: [cid, ...]}, ...]
    """
    try:
        from datasets import load_dataset
    except ImportError as e:
        raise RuntimeError(
            "缺少 datasets 依赖。请在 api/ 下执行：uv sync（已在 pyproject.toml 加入）"
        ) from e

    cache_dir = str(cache_path("hf_datasets").parent)  # HF 自管缓存目录

    # 加载 corpus
    ds_corpus = load_dataset(_HF_REPO, "corpus", cache_dir=cache_dir, split="corpus")
    corpus: list[CMTEBCorpusItem] = []
    for i, row in enumerate(ds_corpus):
        if corpus_limit is not None and i >= corpus_limit:
            break
        cid = str(row.get("_id") or row.get("id") or i)
        corpus.append({
            "cid": cid,
            "title": (row.get("title") or "").strip(),
            "text": (row.get("text") or "").strip(),
        })

    # 加载 queries（按 split）
    ds_queries = load_dataset(_HF_REPO, "queries", cache_dir=cache_dir, split="queries")
    qmap: dict[str, str] = {}
    for row in ds_queries:
        qid = str(row.get("_id") or row.get("id"))
        qmap[qid] = (row.get("text") or "").strip()

    # 加载 qrels（标注）—— 形如 {query-id, corpus-id, score}
    ds_qrels = load_dataset(_HF_REPO, cache_dir=cache_dir, split=split)
    qrel_by_query: dict[str, list[str]] = {}
    for row in ds_qrels:
        qid = str(row.get("query-id") or row.get("query_id"))
        cid = str(row.get("corpus-id") or row.get("corpus_id"))
        score = float(row.get("score") or 1.0)
        if score <= 0:
            continue
        qrel_by_query.setdefault(qid, []).append(cid)

    # 装配 query 集
    queries: list[CMTEBQuery] = []
    for qid, rel_cids in qrel_by_query.items():
        if qid not in qmap:
            continue
        queries.append({"qid": qid, "text": qmap[qid], "relevant_doc_ids": rel_cids})
    if query_limit is not None:
        queries = queries[:query_limit]

    return {"corpus": corpus, "queries": queries, "split": split}
