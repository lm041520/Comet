"""知识库文档业务服务：上传/网页导入/列表/状态/重试/删除/检索。"""
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError
from app.core.logging import get_logger
from app.core.rag.es_store import delete_by_source
from app.core.rag.parser import SUPPORTED_EXTS
from app.core.rag.search import hybrid_search
from app.core.storage import build_file_key, get_storage
from app.models.document_model import (
    DOC_STATUS_PENDING,
    Document,
)
from app.repositories.document_repository import DocumentRepository
from app.repositories.tag_repository import TagRepository

logger = get_logger(__name__)

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


class DocumentService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = DocumentRepository(session)
        self.tag_repo = TagRepository(session)

    async def _dispatch_parse(self, document_id: uuid.UUID) -> None:
        # 延迟导入，避免 worker 未装时影响导入
        from app.tasks.parse import parse_document_task

        parse_document_task.delay(str(document_id))

    async def upload(
        self, user_id: uuid.UUID, file_name: str, content: bytes
    ) -> Document:
        ext = Path(file_name).suffix.lower()
        if ext not in SUPPORTED_EXTS:
            raise BizError(f"不支持的文件类型: {ext}", code=3001)
        if len(content) > MAX_FILE_SIZE:
            raise BizError("文件超过 50MB 限制", code=3005)

        doc_id = uuid.uuid4()
        file_key = build_file_key(str(user_id), "documents", str(doc_id), ext)
        await get_storage().save(file_key, content)

        doc = Document(
            id=doc_id,
            user_id=user_id,
            file_name=file_name,
            file_ext=ext,
            file_size=len(content),
            file_key=file_key,
            source_type="file",
            status=DOC_STATUS_PENDING,
        )
        await self.repo.create(doc)
        await self._dispatch_parse(doc_id)
        logger.info("文档上传: user=%s id=%s name=%s", user_id, doc_id, file_name)
        return doc

    async def import_url(self, user_id: uuid.UUID, url: str) -> Document:
        from app.core.rag.web_crawler import fetch_url_content

        title, text = await fetch_url_content(url)
        doc_id = uuid.uuid4()
        file_key = build_file_key(str(user_id), "documents", str(doc_id), ".txt")
        await get_storage().save(file_key, text.encode("utf-8"))

        doc = Document(
            id=doc_id,
            user_id=user_id,
            file_name=f"{title}.txt",
            file_ext=".txt",
            file_size=len(text.encode("utf-8")),
            file_key=file_key,
            source_type="url",
            source_url=url,
            status=DOC_STATUS_PENDING,
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
        self, user_id: uuid.UUID, page: int, page_size: int, tag: str | None = None
    ) -> tuple[list[Document], int]:
        return await self.repo.list_paged(user_id, page, page_size, tag)

    async def get_detail(self, user_id: uuid.UUID, doc_id: uuid.UUID) -> Document:
        return await self._get_or_404(user_id, doc_id)

    async def retry(self, user_id: uuid.UUID, doc_id: uuid.UUID) -> Document:
        doc = await self._get_or_404(user_id, doc_id)
        doc.status = DOC_STATUS_PENDING
        doc.progress = 0.0
        doc.error_msg = None
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
    ) -> list[dict]:
        return await hybrid_search(
            self.session,
            user_id,
            query,
            top_k=top_k,
            tags=tags,
            source_type="document",
        )

    async def to_out_dict(self, doc: Document) -> dict:
        tags = await self.tag_repo.get_document_tags(doc.id)
        return {
            "id": str(doc.id),
            "file_name": doc.file_name,
            "file_ext": doc.file_ext,
            "file_size": doc.file_size,
            "source_type": doc.source_type,
            "source_url": doc.source_url,
            "status": doc.status,
            "progress": doc.progress,
            "chunk_num": doc.chunk_num,
            "error_msg": doc.error_msg,
            "tags": tags,
            "created_at": doc.created_at.isoformat(),
        }
