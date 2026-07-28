"""Block 感知父子分块。"""

import re

import tiktoken

from app.core.rag.chunking.models import ParentChunk, RetrievalChunk
from app.core.rag.ingestion.models import BlockType, DocumentBlock

CHILD_CHUNK_TOKENS = 256
PARENT_CHUNK_TOKENS = 1024
CHILD_OVERLAP_RATIO = 0.1

_SENT_SEP = re.compile(r"(?<=[。！？\.\!\?\n])")
_encoder = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_encoder.encode(text))


def _split_sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENT_SEP.split(text) if part and part.strip()]


def _split_token_window(
    text: str,
    target_tokens: int,
    overlap_ratio: float = 0.0,
) -> list[str]:
    token_ids = _encoder.encode(text)
    if not token_ids:
        return []
    overlap = int(target_tokens * overlap_ratio)
    step = max(1, target_tokens - overlap)
    return [
        _encoder.decode(token_ids[start : start + target_tokens]).strip()
        for start in range(0, len(token_ids), step)
        if token_ids[start : start + target_tokens]
    ]


def _merge_to_chunks(
    sentences: list[str],
    target_tokens: int,
    overlap_ratio: float = 0.0,
) -> list[str]:
    """按句子边界合并；超长单句按 token 窗口切分。"""
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for sentence in sentences:
        sentence_tokens = count_tokens(sentence)
        if sentence_tokens >= target_tokens:
            if current:
                chunks.append("".join(current))
                current, current_tokens = [], 0
            chunks.extend(_split_token_window(sentence, target_tokens, overlap_ratio))
            continue
        if current_tokens + sentence_tokens > target_tokens and current:
            chunks.append("".join(current))
            if overlap_ratio > 0:
                keep = max(1, int(len(current) * overlap_ratio))
                current = current[-keep:]
                current_tokens = sum(count_tokens(item) for item in current)
            else:
                current, current_tokens = [], 0
        current.append(sentence)
        current_tokens += sentence_tokens
    if current:
        chunks.append("".join(current))
    return chunks


def _metadata_for_blocks(blocks: list[DocumentBlock]) -> dict:
    page_starts = [block.page_start for block in blocks if block.page_start is not None]
    page_ends = [block.page_end for block in blocks if block.page_end is not None]
    heading_path: list[str] = []
    for block in blocks:
        if block.heading_path:
            heading_path = block.heading_path
    return {
        "block_ids": [block.block_id for block in blocks],
        "block_types": list(dict.fromkeys(block.block_type.value for block in blocks)),
        "page_start": min(page_starts) if page_starts else None,
        "page_end": max(page_ends) if page_ends else None,
        "heading_path": list(heading_path),
    }


def _build_parent(blocks: list[DocumentBlock], parent_index: int) -> ParentChunk:
    content = "\n".join(block.content for block in blocks if block.content)
    metadata = _metadata_for_blocks(blocks)
    child_texts = _merge_to_chunks(
        _split_sentences(content),
        CHILD_CHUNK_TOKENS,
        CHILD_OVERLAP_RATIO,
    )
    child_chunks = [
        RetrievalChunk(
            content=child_text,
            block_ids=metadata["block_ids"],
            block_types=metadata["block_types"],
            page_start=metadata["page_start"],
            page_end=metadata["page_end"],
            heading_path=metadata["heading_path"],
            chunk_index=child_index,
        )
        for child_index, child_text in enumerate(child_texts)
    ]
    return ParentChunk(
        content=content,
        child_chunks=child_chunks,
        block_ids=metadata["block_ids"],
        block_types=metadata["block_types"],
        page_start=metadata["page_start"],
        page_end=metadata["page_end"],
        heading_path=metadata["heading_path"],
        chunk_index=parent_index,
    )


def chunk_blocks(blocks: list[DocumentBlock]) -> list[ParentChunk]:
    """按标题路径和 Block 边界构建父块，表格单独保护。"""
    groups: list[list[DocumentBlock]] = []
    current: list[DocumentBlock] = []
    current_tokens = 0
    current_heading: list[str] = []

    def flush() -> None:
        nonlocal current, current_tokens, current_heading
        if current:
            groups.append(current)
        current = []
        current_tokens = 0
        current_heading = []

    for block in blocks:
        if not block.content.strip():
            continue
        block_tokens = count_tokens(block.content)
        if block.block_type == BlockType.TABLE:
            flush()
            if block_tokens <= PARENT_CHUNK_TOKENS:
                groups.append([block])
            else:
                for part in _split_token_window(block.content, PARENT_CHUNK_TOKENS):
                    groups.append(
                        [
                            DocumentBlock(
                                content=part,
                                block_type=block.block_type,
                                block_id=block.block_id,
                                page_start=block.page_start,
                                page_end=block.page_end,
                                heading_path=block.heading_path,
                                metadata=block.metadata,
                            )
                        ]
                    )
            continue
        if block_tokens > PARENT_CHUNK_TOKENS:
            flush()
            for part in _split_token_window(block.content, PARENT_CHUNK_TOKENS):
                groups.append(
                    [
                        DocumentBlock(
                            content=part,
                            block_type=block.block_type,
                            block_id=block.block_id,
                            page_start=block.page_start,
                            page_end=block.page_end,
                            heading_path=block.heading_path,
                            metadata=block.metadata,
                        )
                    ]
                )
            continue
        heading_changed = bool(current) and block.heading_path != current_heading
        size_exceeded = bool(current) and current_tokens + block_tokens > PARENT_CHUNK_TOKENS
        if heading_changed or size_exceeded:
            flush()
        if not current:
            current_heading = list(block.heading_path)
        current.append(block)
        current_tokens += block_tokens
    flush()

    return [_build_parent(group, index) for index, group in enumerate(groups)]


def chunk_parent_child(text: str) -> list[ParentChunk]:
    """兼容旧接口，把纯文本包装成单个 Block 后切块。"""
    if not text.strip():
        return []
    return chunk_blocks([DocumentBlock(content=text.strip())])
