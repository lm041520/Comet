"""普通 PDF 的低成本 PyMuPDF 结构化解析器。"""

from statistics import median

from app.core.rag.ingestion.models import (
    BlockType,
    DocumentBlock,
    DocumentProfile,
    ParsedDocument,
)
from app.core.rag.ingestion.parsers.base import BaseDocumentParser, DocumentParseError


class PyMuPDFParser(BaseDocumentParser):
    name = "pymupdf"
    version = "2"
    supported_exts = frozenset({".pdf"})

    def parse(self, content: bytes, profile: DocumentProfile) -> ParsedDocument:
        try:
            import fitz

            blocks: list[DocumentBlock] = []
            with fitz.open(stream=content, filetype="pdf") as document:
                for page_index, page in enumerate(document):
                    blocks.extend(self._parse_page(page, page_index + 1))
        except Exception as exc:
            raise DocumentParseError("PDF 文档解析失败") from exc
        warnings: list[str] = []
        if profile.scanned_pdf_risk:
            warnings.append("PDF 文本密度较低，可能是扫描件")
        return ParsedDocument(
            blocks=blocks,
            parser_name=self.name,
            parser_version=self.version,
            warnings=warnings,
            profile=profile,
        )

    @staticmethod
    def _parse_page(page, page_number: int) -> list[DocumentBlock]:
        raw_blocks: list[tuple[str, list[float], float]] = []
        font_sizes: list[float] = []
        for item in page.get_text("dict").get("blocks", []):
            if item.get("type") != 0:
                continue
            lines: list[str] = []
            item_sizes: list[float] = []
            for line in item.get("lines", []):
                spans = line.get("spans", [])
                line_text = "".join(span.get("text", "") for span in spans).strip()
                if line_text:
                    lines.append(line_text)
                item_sizes.extend(float(span.get("size", 0)) for span in spans)
            text = "\n".join(lines).strip()
            if not text:
                continue
            block_size = max(item_sizes, default=0.0)
            font_sizes.extend(size for size in item_sizes if size > 0)
            raw_blocks.append((text, list(item.get("bbox", [])), block_size))

        body_size = median(font_sizes) if font_sizes else 0.0
        result: list[DocumentBlock] = []
        for text, bbox, block_size in raw_blocks:
            is_heading = (
                body_size > 0 and block_size >= max(14.0, body_size * 1.2) and len(text) <= 120
            )
            metadata: dict = {"bbox": bbox, "font_size": round(block_size, 2)}
            block_type = BlockType.PARAGRAPH
            if is_heading:
                block_type = BlockType.HEADING
                ratio = block_size / body_size
                metadata["heading_level"] = 1 if ratio >= 1.8 else 2 if ratio >= 1.4 else 3
            result.append(
                DocumentBlock(
                    content=text,
                    block_type=block_type,
                    order=len(result),
                    page_start=page_number,
                    page_end=page_number,
                    metadata=metadata,
                )
            )
        return result
