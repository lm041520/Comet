"""文档解析流水线使用的统一中间模型。"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
import uuid


class BlockType(StrEnum):
    """解析器能够输出的通用文档结构类型。"""

    TITLE = "title"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"
    IMAGE = "image"
    CODE = "code"
    OTHER = "other"


class ParseStatus(StrEnum):
    """文档解析结果状态。"""

    OK = "ok"
    WARNING = "warning"
    FALLBACK = "fallback"
    FAILED = "failed"


@dataclass(slots=True)
class DocumentProfile:
    """低成本文件体检结果，不包含持久化和检索逻辑。"""

    file_ext: str
    file_size: int
    page_count: int | None = None
    text_char_count: int = 0
    image_count: int = 0
    text_density: float | None = None
    scanned_pdf_risk: bool = False
    features: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DocumentBlock:
    """解析阶段得到的自然结构单元。"""

    content: str
    block_type: BlockType = BlockType.PARAGRAPH
    order: int = 0
    block_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    page_start: int | None = None
    page_end: int | None = None
    heading_path: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedDocument:
    """不同解析器统一返回的结构化文档。"""

    blocks: list[DocumentBlock]
    parser_name: str
    parser_version: str
    status: ParseStatus = ParseStatus.OK
    warnings: list[str] = field(default_factory=list)
    profile: DocumentProfile | None = None
    parse_summary: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        """兼容旧链路的纯文本视图。"""
        return "\n".join(block.content for block in self.blocks if block.content)
