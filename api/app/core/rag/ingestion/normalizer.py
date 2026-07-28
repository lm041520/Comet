"""将解析器输出整理为稳定、有序的 DocumentBlock 列表。"""

from app.core.rag.ingestion.models import BlockType, DocumentBlock, ParsedDocument


def normalize_parsed_document(parsed: ParsedDocument) -> ParsedDocument:
    """清理空 Block、补齐顺序、页码和标题路径。"""
    normalized: list[DocumentBlock] = []
    heading_stack: list[str] = []
    for block in parsed.blocks:
        content = block.content.strip() if block.content else ""
        if not content:
            continue
        block.content = content
        block.order = len(normalized)
        if block.page_start is not None and block.page_end is None:
            block.page_end = block.page_start

        if block.block_type in {BlockType.TITLE, BlockType.HEADING}:
            level = int(block.metadata.get("heading_level", 1))
            level = max(1, min(level, 6))
            heading_stack = heading_stack[: level - 1]
            heading_stack.append(block.content)
            block.heading_path = list(heading_stack)
        elif not block.heading_path:
            block.heading_path = list(heading_stack)
        normalized.append(block)

    parsed.blocks = normalized
    parsed.parse_summary.update(
        {
            "block_count": len(normalized),
            "block_types": sorted({block.block_type.value for block in normalized}),
        }
    )
    return parsed
