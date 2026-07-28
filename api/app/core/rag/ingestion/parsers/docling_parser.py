"""复杂 PDF 的 Docling 解析器适配。"""

from functools import lru_cache
from importlib.util import find_spec
from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
import os
from pathlib import Path
from typing import Any

from app.config import settings
from app.core.rag.ingestion.models import (
    BlockType,
    DocumentBlock,
    DocumentProfile,
    ParsedDocument,
)
from app.core.rag.ingestion.enrichers.image_enricher import evaluate_image_value
from app.core.rag.ingestion.parsers.base import BaseDocumentParser, DocumentParseError

_runtime_error: str | None = None


def _label_value(item: Any) -> str:
    label = getattr(item, "label", "")
    return str(getattr(label, "value", label)).lower()


def _provenance(item: Any) -> tuple[int | None, dict[str, float] | None]:
    provenance = getattr(item, "prov", None) or []
    if not provenance:
        return None, None
    source = provenance[0]
    page_number = getattr(source, "page_no", None)
    bbox = getattr(source, "bbox", None)
    if bbox is None:
        return page_number, None
    if hasattr(bbox, "model_dump"):
        return page_number, bbox.model_dump()
    return page_number, None


@lru_cache(maxsize=1)
def _build_converter():
    cache_dir = Path(settings.rag_docling_cache_dir).resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(cache_dir / "huggingface"))
    os.environ.setdefault("DOCLING_CACHE_DIR", str(cache_dir))

    # 模型不进 git，缺失则本进程尝试自动下载一次；失败则抛错，由上层降级 PyMuPDF
    from app.core.rag.ingestion.parsers.docling_models import ensure_docling_models

    download_error = ensure_docling_models(cache_dir)
    if download_error:
        raise RuntimeError(f"Docling 模型不可用：{download_error}")

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = PdfPipelineOptions(
        artifacts_path=cache_dir,
        do_ocr=settings.rag_docling_do_ocr,
        ocr_options=RapidOcrOptions(backend="onnxruntime"),
        do_table_structure=True,
        generate_picture_images=False,
    )
    return DocumentConverter(
        allowed_formats=[InputFormat.PDF],
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=options),
        },
    )


class DoclingParser(BaseDocumentParser):
    name = "docling"
    supported_exts = frozenset({".pdf"})

    @property
    def version(self) -> str:
        try:
            return version("docling")
        except PackageNotFoundError:
            return "unavailable"

    @staticmethod
    def is_available() -> bool:
        if _runtime_error is not None:
            return False
        return find_spec("docling") is not None

    @staticmethod
    def runtime_error() -> str | None:
        return _runtime_error

    def parse(self, content: bytes, profile: DocumentProfile) -> ParsedDocument:
        global _runtime_error
        if not self.is_available():
            detail = f"：{_runtime_error}" if _runtime_error else ""
            raise DocumentParseError(f"Docling 未安装或不可用{detail}")
        try:
            from docling.datamodel.base_models import DocumentStream

            source = DocumentStream(
                name="uploaded.pdf",
                stream=BytesIO(content),
            )
            result = _build_converter().convert(
                source,
                max_num_pages=settings.rag_docling_max_pages,
                max_file_size=settings.rag_docling_max_file_size,
            )
            document = result.document
            blocks = self._to_blocks(document)
        except Exception as exc:
            _runtime_error = str(exc)[:500]
            raise DocumentParseError(f"Docling 解析失败: {exc}") from exc

        table_count = sum(block.block_type == BlockType.TABLE for block in blocks)
        picture_count = sum(block.block_type == BlockType.IMAGE for block in blocks)
        return ParsedDocument(
            blocks=blocks,
            parser_name=self.name,
            parser_version=self.version,
            profile=profile,
            parse_summary={
                "table_count": table_count,
                "picture_count": picture_count,
            },
        )

    @staticmethod
    def _to_blocks(document: Any) -> list[DocumentBlock]:
        blocks: list[DocumentBlock] = []
        for item, level in document.iterate_items():
            label = _label_value(item)
            page_number, bbox = _provenance(item)
            metadata: dict[str, Any] = {
                "docling_label": label,
                "hierarchy_level": level,
            }
            if bbox is not None:
                metadata["bbox"] = bbox

            block_type = BlockType.OTHER
            text = str(getattr(item, "text", "") or "").strip()
            if label in {"title", "document_index"}:
                block_type = BlockType.TITLE
                metadata["heading_level"] = 1
            elif label in {"section_header", "heading"}:
                block_type = BlockType.HEADING
                metadata["heading_level"] = max(1, min(int(level or 1), 6))
            elif label in {"list_item"}:
                block_type = BlockType.LIST
            elif label in {"code"}:
                block_type = BlockType.CODE
            elif label in {"table"}:
                block_type = BlockType.TABLE
                text = item.export_to_markdown(doc=document).strip()
            elif label in {"picture"}:
                block_type = BlockType.IMAGE
                caption = ""
                if hasattr(item, "caption_text"):
                    caption = str(item.caption_text(document) or "").strip()
                text = caption or "[图片]"
                metadata["needs_image_enrichment"] = bool(not caption)
            elif text:
                block_type = BlockType.PARAGRAPH
            else:
                continue

            block = DocumentBlock(
                content=text,
                block_type=block_type,
                order=len(blocks),
                page_start=page_number,
                page_end=page_number,
                metadata=metadata,
            )
            if block_type == BlockType.IMAGE:
                decision = evaluate_image_value(block)
                block.metadata.update(
                    {
                        "should_enrich": decision.should_enrich,
                        "image_category": decision.category,
                        "enrichment_reason": decision.reason,
                    }
                )
            blocks.append(block)
        return blocks
