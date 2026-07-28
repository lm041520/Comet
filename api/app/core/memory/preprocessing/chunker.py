"""记忆文本分块：把一段来源文本切成 ~512 token 的块逐块萃取。

短文本整体作为一块；长文本按句子边界贪心聚合，块间不重叠。
复用 RAG 的 tiktoken token 计数，保证与知识库分块口径一致。
"""
import re

from app.core.rag.chunking.block_chunker import count_tokens

# 记忆分块目标 token 数
MEMORY_CHUNK_TOKENS = 512

_SENT_SEP = re.compile(r"(?<=[。！？\.\!\?\n])")


def split_chunks(text: str) -> list[str]:
    """按句子聚合成 ~MEMORY_CHUNK_TOKENS 的块。短文本整体作为一块。"""
    text = (text or "").strip()
    if not text:
        return []
    if count_tokens(text) <= MEMORY_CHUNK_TOKENS:
        return [text]
    parts = [p.strip() for p in _SENT_SEP.split(text) if p and p.strip()]
    chunks: list[str] = []
    cur: list[str] = []
    cur_tokens = 0
    for part in parts:
        pt = count_tokens(part)
        if cur_tokens + pt > MEMORY_CHUNK_TOKENS and cur:
            chunks.append("".join(cur))
            cur, cur_tokens = [], 0
        cur.append(part)
        cur_tokens += pt
    if cur:
        chunks.append("".join(cur))
    return chunks


__all__ = ["MEMORY_CHUNK_TOKENS", "split_chunks"]
