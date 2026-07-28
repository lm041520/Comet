"""文档解析器统一接口。"""

from abc import ABC, abstractmethod

from app.core.rag.ingestion.models import DocumentProfile, ParsedDocument


class DocumentParseError(Exception):
    """解析器执行失败，供流水线统一转换为业务错误。"""


class BaseDocumentParser(ABC):
    name = "base"
    version = "1"
    supported_exts: frozenset[str] = frozenset()

    def supports(self, profile: DocumentProfile) -> bool:
        return profile.file_ext in self.supported_exts

    @abstractmethod
    def parse(self, content: bytes, profile: DocumentProfile) -> ParsedDocument:
        """把文件内容解析为统一结构化文档。"""
