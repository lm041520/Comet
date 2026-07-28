"""知识库文档业务服务：上传/网页导入/列表/状态/重试/删除/检索。"""
import hashlib
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError
from app.core.logging import get_logger
from app.core.rag.ingestion import parse_document_structured
from app.core.rag.ingestion.parsers.plain_parser import decode_text
from app.core.rag.ingestion.router import ParserRouter
from app.core.rag.indexing.es_store import delete_by_source
from app.core.rag.retrieval import hybrid_search, hybrid_search_with_trace
from app.core.storage import build_file_key, get_storage
from app.models.document_model import (
    DOC_STATUS_PENDING,
    Document,
)
from app.repositories.document_repository import DocumentRepository
from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.repositories.tag_repository import TagRepository

logger = get_logger(__name__)

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
SUPPORTED_EXTS = ParserRouter().supported_exts


class DocumentService:
    PREVIEW_MAX_CHARS = 80000  # 文档预览最大返回字符数（超出截断）
    PREVIEW_URL_EXPIRES_SECONDS = 600

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = DocumentRepository(session)
        self.tag_repo = TagRepository(session)
        self.kb_repo = KnowledgeBaseRepository(session)

    async def _dispatch_parse(self, document_id: uuid.UUID) -> None:
        # 延迟导入，避免 worker 未装时影响导入
        from app.tasks.parse import parse_document_task

        parse_document_task.delay(str(document_id))

    async def _resolve_kb_id(
        self, user_id: uuid.UUID, kb_id: uuid.UUID | None
    ) -> uuid.UUID:
        """确定文档归属库：指定了就校验归属，没指定落默认库。"""
        if kb_id:
            kb = await self.kb_repo.get(user_id, kb_id)
            if not kb:
                raise BizError("知识库不存在", code=3040, status_code=404)
            return kb.id
        return (await self.kb_repo.ensure_default(user_id)).id

    async def upload(
        self,
        user_id: uuid.UUID,
        file_name: str,
        content: bytes,
        kb_id: uuid.UUID | None = None,
    ) -> Document:
        ext = Path(file_name).suffix.lower()
        if ext not in SUPPORTED_EXTS:
            raise BizError(f"不支持的文件类型: {ext}", code=3001)
        if len(content) > MAX_FILE_SIZE:
            raise BizError("文件超过 50MB 限制", code=3005)

        resolved_kb = await self._resolve_kb_id(user_id, kb_id)
        doc_id = uuid.uuid4()
        file_key = build_file_key(str(user_id), "documents", str(doc_id), ext)
        await get_storage().save(file_key, content)

        doc = Document(
            id=doc_id,
            user_id=user_id,
            kb_id=resolved_kb,
            file_name=file_name,
            file_ext=ext,
            file_size=len(content),
            file_key=file_key,
            source_type="file",
            status=DOC_STATUS_PENDING,
            content_hash=hashlib.sha256(content).hexdigest(),
        )
        await self.repo.create(doc)
        await self._dispatch_parse(doc_id)
        logger.info("文档上传: user=%s id=%s name=%s", user_id, doc_id, file_name)
        return doc

    async def import_url(
        self, user_id: uuid.UUID, url: str, kb_id: uuid.UUID | None = None
    ) -> Document:
        from app.core.rag.web_crawler import fetch_url_content

        resolved_kb = await self._resolve_kb_id(user_id, kb_id)
        title, text = await fetch_url_content(url)
        doc_id = uuid.uuid4()
        file_key = build_file_key(str(user_id), "documents", str(doc_id), ".txt")
        encoded_text = text.encode("utf-8")
        await get_storage().save(file_key, encoded_text)

        doc = Document(
            id=doc_id,
            user_id=user_id,
            kb_id=resolved_kb,
            file_name=f"{title}.txt",
            file_ext=".txt",
            file_size=len(encoded_text),
            file_key=file_key,
            source_type="url",
            source_url=url,
            status=DOC_STATUS_PENDING,
            content_hash=hashlib.sha256(encoded_text).hexdigest(),
        )
        await self.repo.create(doc)
        await self._dispatch_parse(doc_id)
        logger.info("网页导入: user=%s id=%s url=%s", user_id, doc_id, url)
        return doc

    async def _get_or_404(
        self, user_id: uuid.UUID, doc_id: uuid.UUID
    ) -> Document:
        doc = await self.repo.get(user_id, doc_id)
        if not doc:
            raise BizError("文档不存在", code=3006, status_code=404)
        return doc

    async def list_documents(
        self,
        user_id: uuid.UUID,
        page: int,
        page_size: int,
        tag: str | None = None,
        kb_id: uuid.UUID | None = None,
    ) -> tuple[list[Document], int]:
        return await self.repo.list_paged(user_id, page, page_size, tag, kb_id)

    async def get_detail(self, user_id: uuid.UUID, doc_id: uuid.UUID) -> Document:
        return await self._get_or_404(user_id, doc_id)

    async def retry(
        self,
        user_id: uuid.UUID,
        doc_id: uuid.UUID,
        preferred_parser: str = "auto",
    ) -> Document:
        doc = await self._get_or_404(user_id, doc_id)
        if preferred_parser not in {"auto", "plain", "pymupdf", "docling"}:
            raise BizError("不支持的解析器", code=3007)
        doc.status = DOC_STATUS_PENDING
        doc.progress = 0.0
        doc.error_msg = None
        doc.preferred_parser = preferred_parser
        await self.repo.save(doc)
        await self._dispatch_parse(doc_id)
        return doc

    async def delete(self, user_id: uuid.UUID, doc_id: uuid.UUID) -> None:
        doc = await self._get_or_404(user_id, doc_id)
        # 清 ES chunk + 存储文件 + PG 记录
        await delete_by_source(str(user_id), str(doc_id))
        try:
            await get_storage().delete(doc.file_key)
        except Exception as e:
            logger.warning("删除存储文件失败（忽略）: %s", e)
        await self.repo.delete(doc)
        logger.info("删除文档: user=%s id=%s", user_id, doc_id)

    async def search(
        self,
        user_id: uuid.UUID,
        query: str,
        top_k: int,
        tags: list[str] | None,
        kb_id: uuid.UUID | None = None,
    ) -> list[dict]:
        if kb_id is not None and not await self.kb_repo.get(user_id, kb_id):
            raise BizError("知识库不存在", code=3040, status_code=404)
        return await hybrid_search(
            self.session,
            user_id,
            query,
            top_k=top_k,
            tags=tags,
            source_type="document",
            kb_ids=[str(kb_id)] if kb_id else None,
        )

    async def validate_retrieval(
        self,
        user_id: uuid.UUID,
        kb_id: uuid.UUID,
        query: str,
        top_k: int,
    ) -> dict:
        if not await self.kb_repo.get(user_id, kb_id):
            raise BizError("知识库不存在", code=3040, status_code=404)
        return await hybrid_search_with_trace(
            self.session,
            user_id,
            query,
            kb_id=kb_id,
            top_k=top_k,
        )

    async def move_to_kb(
        self, user_id: uuid.UUID, doc_id: uuid.UUID, kb_id: uuid.UUID
    ) -> Document:
        """把文档移动到另一个知识库，并同步回写 ES chunk 的 kb_id。"""
        from app.core.rag.indexing.es_store import update_kb_by_source

        doc = await self._get_or_404(user_id, doc_id)
        kb = await self.kb_repo.get(user_id, kb_id)
        if not kb:
            raise BizError("知识库不存在", code=3040, status_code=404)
        doc.kb_id = kb.id
        await self.repo.save(doc)
        try:
            await update_kb_by_source(str(user_id), str(doc_id), str(kb.id))
        except Exception as e:
            logger.warning("移动文档回写 ES kb_id 失败（忽略）: %s", e)
        return doc

    async def preview(self, user_id: uuid.UUID, doc_id: uuid.UUID) -> dict:
        """获取原文件预览：PDF 返回鉴权预览地址，其余格式返回文本内容。

        PDF 不重新执行结构化解析；上传时的 Block/Chunk 与预览职责保持分离。
        """
        doc = await self._get_or_404(user_id, doc_id)
        ext = (doc.file_ext or "").lower()
        is_markdown = ext in (".md", ".markdown")
        storage = get_storage()
        if ext == ".pdf":
            expires = self.PREVIEW_URL_EXPIRES_SECONDS
            return {
                "id": str(doc.id),
                "file_name": doc.file_name,
                "file_ext": ext,
                "preview_type": "pdf",
                "preview_url": f"/api/documents/{doc.id}/preview-file",
                "download_url": storage.get_url(doc.file_key, expires=expires),
                "expires_in": expires,
                "is_markdown": False,
                "source_url": doc.source_url,
                "content": "",
                "truncated": False,
            }

        try:
            raw = await storage.get(doc.file_key)
        except Exception as e:
            logger.warning("读取文档原文失败: id=%s err=%s", doc_id, e)
            raise BizError("原始文件读取失败，可能已被清理", code=3033) from e

        try:
            if is_markdown or ext == ".txt":
                # 保留原始文本（markdown 交前端渲染，纯文本原样展示）
                text = decode_text(raw)
            else:
                text = parse_document_structured(ext, raw).text
        except Exception as e:
            logger.warning("文档预览解析失败: id=%s err=%s", doc_id, e)
            raise BizError(f"内容解析失败：{e}", code=3034) from e

        text = (text or "").strip()
        truncated = len(text) > self.PREVIEW_MAX_CHARS
        if truncated:
            text = text[: self.PREVIEW_MAX_CHARS]
        return {
            "id": str(doc.id),
            "file_name": doc.file_name,
            "file_ext": ext,
            "preview_type": "text",
            "preview_url": None,
            "download_url": None,
            "expires_in": None,
            "is_markdown": is_markdown,
            "source_url": doc.source_url,
            "content": text,
            "truncated": truncated,
        }

    async def get_preview_file(
        self, user_id: uuid.UUID, doc_id: uuid.UUID
    ) -> tuple[Document, bytes]:
        """读取 PDF 原始字节供浏览器预览，不触发结构化解析或切片。"""
        doc = await self._get_or_404(user_id, doc_id)
        if (doc.file_ext or "").lower() != ".pdf":
            raise BizError("仅 PDF 文件支持原文件预览", code=3035, status_code=400)
        try:
            content = await get_storage().get(doc.file_key)
        except Exception as e:
            logger.warning("读取 PDF 预览原文件失败: id=%s err=%s", doc_id, e)
            raise BizError("原始文件读取失败，可能已被清理", code=3033) from e
        return doc, content

    async def to_out_dict(self, doc: Document) -> dict:
        tags = await self.tag_repo.get_document_tags(doc.id)
        return {
            "id": str(doc.id),
            "kb_id": str(doc.kb_id) if doc.kb_id else None,
            "file_name": doc.file_name,
            "file_ext": doc.file_ext,
            "file_size": doc.file_size,
            "source_type": doc.source_type,
            "source_url": doc.source_url,
            "status": doc.status,
            "progress": doc.progress,
            "chunk_num": doc.chunk_num,
            "error_msg": doc.error_msg,
            "content_hash": doc.content_hash,
            "preferred_parser": doc.preferred_parser,
            "parser_name": doc.parser_name,
            "parser_version": doc.parser_version,
            "parse_status": doc.parse_status,
            "parse_summary": doc.parse_summary or {},
            "parsed_at": doc.parsed_at.isoformat() if doc.parsed_at else None,
            "tags": tags,
            "created_at": doc.created_at.isoformat(),
        }
