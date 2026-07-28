"""检索切块使用的中间模型。"""

from dataclasses import dataclass, field


@dataclass(slots=True)
class RetrievalChunk:
    """可写入检索索引的子 Chunk。"""

    content: str
    chunk_type: str = "child"
    parent_id: str | None = None
    block_ids: list[str] = field(default_factory=list)
    block_types: list[str] = field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    heading_path: list[str] = field(default_factory=list)
    chunk_index: int = 0


@dataclass(slots=True)
class ParentChunk:
    """父上下文及其可召回子 Chunk。"""

    content: str
    child_chunks: list[RetrievalChunk] = field(default_factory=list)
    block_ids: list[str] = field(default_factory=list)
    block_types: list[str] = field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    heading_path: list[str] = field(default_factory=list)
    chunk_index: int = 0

    @property
    def children(self) -> list[str]:
        """兼容旧调用方的纯文本子块列表。"""
        return [chunk.content for chunk in self.child_chunks]
