"""文档结构化解析流水线。"""

from app.core.exceptions import BizError
from app.core.rag.ingestion.inspector import FileInspector
from app.core.rag.ingestion.models import ParsedDocument, ParseStatus
from app.core.rag.ingestion.normalizer import normalize_parsed_document
from app.core.rag.ingestion.parsers.base import DocumentParseError
from app.core.rag.ingestion.parsers.pymupdf_parser import PyMuPDFParser
from app.core.rag.ingestion.quality import apply_parse_quality
from app.core.rag.ingestion.router import ParserRouter


def parse_document_structured(
    file_ext: str,
    content: bytes,
    *,
    inspector: FileInspector | None = None,
    router: ParserRouter | None = None,
    preferred_parser: str | None = None,
) -> ParsedDocument:
    """执行文件体检、解析器路由、解析、回退、规范化和质量判断。"""
    active_inspector = inspector or FileInspector()
    active_router = router or ParserRouter()
    profile = active_inspector.inspect(file_ext, content)
    parser = active_router.select(profile, preferred_parser)
    try:
        parsed = parser.parse(content, profile)
    except DocumentParseError as exc:
        if parser.name != "docling":
            raise BizError(str(exc), code=3002) from exc
        fallback = PyMuPDFParser()
        try:
            parsed = fallback.parse(content, profile)
        except DocumentParseError as fallback_exc:
            raise BizError(str(fallback_exc), code=3002) from fallback_exc
        parsed.status = ParseStatus.FALLBACK
        parsed.warnings.insert(0, f"Docling 失败，已回退 PyMuPDF：{exc}")
        parsed.parse_summary["fallback_from"] = "docling"

    route_warning = profile.features.get("route_warning")
    if route_warning:
        parsed.warnings.append(str(route_warning))
    parsed.parse_summary["route_reason"] = profile.features.get("route_reason")
    parsed = normalize_parsed_document(parsed)
    parsed = apply_parse_quality(parsed)
    if parsed.status == ParseStatus.FAILED:
        raise BizError("解析结果为空", code=3002)
    return parsed
