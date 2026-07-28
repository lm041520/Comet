"""TXT、Markdown、HTML 与 DOCX 的结构化基础解析器。"""

import io
import re

import chardet

from app.core.rag.ingestion.models import (
    BlockType,
    DocumentBlock,
    DocumentProfile,
    ParsedDocument,
)
from app.core.rag.ingestion.parsers.base import BaseDocumentParser, DocumentParseError


def decode_text(content: bytes) -> str:
    """按检测到的编码解码文本，并在编码异常时回退 UTF-8。"""
    detected = chardet.detect(content)
    encoding = detected.get("encoding") or "utf-8"
    try:
        return content.decode(encoding, errors="ignore")
    except (LookupError, UnicodeDecodeError):
        return content.decode("utf-8", errors="ignore")


def _text_block(
    content: str,
    block_type: BlockType = BlockType.PARAGRAPH,
    **metadata,
) -> DocumentBlock:
    return DocumentBlock(
        content=content.strip(),
        block_type=block_type,
        metadata=metadata,
    )


def _html_to_blocks(raw_html: str) -> list[DocumentBlock]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    blocks: list[DocumentBlock] = []
    for element in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "table"]):
        text = element.get_text(" ", strip=True)
        if not text:
            continue
        if element.name and element.name.startswith("h"):
            blocks.append(
                _text_block(
                    text,
                    BlockType.HEADING,
                    heading_level=int(element.name[1]),
                )
            )
        elif element.name == "li":
            blocks.append(_text_block(text, BlockType.LIST))
        elif element.name == "pre":
            blocks.append(_text_block(text, BlockType.CODE))
        elif element.name == "table":
            rows = []
            for row in element.find_all("tr"):
                cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
                if cells:
                    rows.append(" | ".join(cells))
            blocks.append(
                _text_block(
                    "\n".join(rows) or text,
                    BlockType.TABLE,
                    row_count=len(rows),
                )
            )
        else:
            blocks.append(_text_block(text))
    if blocks:
        return blocks
    text = soup.get_text("\n", strip=True)
    return [_text_block(text)] if text else []


class PlainParser(BaseDocumentParser):
    name = "plain"
    version = "2"
    supported_exts = frozenset({".docx", ".md", ".markdown", ".txt", ".html", ".htm"})

    def parse(self, content: bytes, profile: DocumentProfile) -> ParsedDocument:
        try:
            blocks = self._extract_blocks(profile.file_ext, content)
        except DocumentParseError:
            raise
        except Exception as exc:
            raise DocumentParseError(f"{profile.file_ext} 文档解析失败") from exc
        return ParsedDocument(
            blocks=blocks,
            parser_name=self.name,
            parser_version=self.version,
            profile=profile,
        )

    @staticmethod
    def _extract_blocks(file_ext: str, content: bytes) -> list[DocumentBlock]:
        if file_ext == ".docx":
            return PlainParser._parse_docx(content)
        if file_ext in {".md", ".markdown"}:
            import markdown

            html = markdown.markdown(
                decode_text(content),
                extensions=["tables", "fenced_code"],
            )
            return _html_to_blocks(html)
        if file_ext in {".html", ".htm"}:
            return _html_to_blocks(decode_text(content))
        if file_ext == ".txt":
            paragraphs = [
                part.strip() for part in re.split(r"\n\s*\n", decode_text(content)) if part.strip()
            ]
            return [_text_block(paragraph) for paragraph in paragraphs]
        raise DocumentParseError(f"PlainParser 不支持文件类型: {file_ext}")

    @staticmethod
    def _parse_docx(content: bytes) -> list[DocumentBlock]:
        from docx import Document as DocxDocument
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        document = DocxDocument(io.BytesIO(content))
        blocks: list[DocumentBlock] = []
        for child in document.element.body.iterchildren():
            if child.tag.endswith("}p"):
                paragraph = Paragraph(child, document)
                text = paragraph.text.strip()
                if not text:
                    continue
                style_name = paragraph.style.name if paragraph.style else ""
                match = re.search(r"Heading\s+(\d+)", style_name, re.IGNORECASE)
                if match:
                    blocks.append(
                        _text_block(
                            text,
                            BlockType.HEADING,
                            heading_level=int(match.group(1)),
                        )
                    )
                elif "list" in style_name.lower():
                    blocks.append(_text_block(text, BlockType.LIST))
                else:
                    blocks.append(_text_block(text))
            elif child.tag.endswith("}tbl"):
                table = Table(child, document)
                rows = [" | ".join(cell.text.strip() for cell in row.cells) for row in table.rows]
                rows = [row for row in rows if row.strip(" |")]
                if rows:
                    blocks.append(
                        _text_block(
                            "\n".join(rows),
                            BlockType.TABLE,
                            row_count=len(rows),
                        )
                    )
        return blocks
