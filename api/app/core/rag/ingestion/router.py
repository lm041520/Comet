"""解析器路由：只根据文件特征选择解析器。"""

from collections.abc import Iterable

from app.config import settings
from app.core.exceptions import BizError
from app.core.rag.ingestion.models import DocumentProfile
from app.core.rag.ingestion.parsers.base import BaseDocumentParser
from app.core.rag.ingestion.parsers.docling_parser import DoclingParser
from app.core.rag.ingestion.parsers.plain_parser import PlainParser
from app.core.rag.ingestion.parsers.pymupdf_parser import PyMuPDFParser


class ParserRouter:
    def __init__(self, parsers: Iterable[BaseDocumentParser] | None = None):
        self.parsers = list(parsers or (DoclingParser(), PyMuPDFParser(), PlainParser()))

    @property
    def supported_exts(self) -> set[str]:
        return {file_ext for parser in self.parsers for file_ext in parser.supported_exts}

    def select(
        self,
        profile: DocumentProfile,
        preferred_parser: str | None = None,
    ) -> BaseDocumentParser:
        preferred = preferred_parser or "auto"
        if preferred != "auto":
            selected = self._by_name(preferred)
            if not selected or not selected.supports(profile):
                raise BizError(
                    f"解析器 {preferred} 不支持文件类型: {profile.file_ext}",
                    code=3001,
                )
            if preferred != "docling" or (
                isinstance(selected, DoclingParser) and selected.is_available()
            ):
                profile.features["route_reason"] = f"user_selected_{preferred}"
                return selected
            profile.features["route_warning"] = "指定的 Docling 不可用，使用 PyMuPDF"

        if profile.file_ext == ".pdf":
            if settings.rag_docling_enabled and profile.features.get("advanced_parser_recommended"):
                docling = self._by_name("docling")
                if isinstance(docling, DoclingParser) and docling.is_available():
                    profile.features["route_reason"] = "complex_pdf"
                    return docling
                detail = DoclingParser.runtime_error()
                profile.features["route_warning"] = (
                    f"Docling 不可用，使用 PyMuPDF：{detail}"
                    if detail
                    else "Docling 不可用，使用 PyMuPDF"
                )
            pymupdf = self._by_name("pymupdf")
            if pymupdf:
                profile.features.setdefault("route_reason", "ordinary_pdf")
                return pymupdf

        for parser in self.parsers:
            if parser.name != "docling" and parser.supports(profile):
                return parser
        raise BizError(f"不支持的文件类型: {profile.file_ext}", code=3001)

    def _by_name(self, name: str) -> BaseDocumentParser | None:
        return next((parser for parser in self.parsers if parser.name == name), None)
