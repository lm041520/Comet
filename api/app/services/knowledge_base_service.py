"""知识库业务服务：CRUD + 默认库保障 + 删库级联清理（ES chunk + OSS 文件 + PG）。

删库为物理删除：DB 外键 CASCADE 删除库内 documents/images 的 PG 记录，
但 ES 向量 chunk 与对象存储文件需在 service 层显式清理（DB 不感知）。
默认库不可删、不可被当作普通库随意改名删除（名称可改，但 is_default 不变）。
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError
from app.core.logging import get_logger
from app.core.rag.indexing.es_store import delete_by_source
from app.core.storage import get_storage
from app.models.knowledge_base_model import KnowledgeBase
from app.repositories.document_repository import DocumentRepository
from app.repositories.image_repository import ImageRepository
from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.schemas.knowledge_base_schema import (
    KnowledgeBaseCreate,
    KnowledgeBaseUpdate,
)

logger = get_logger(__name__)


class KnowledgeBaseService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = KnowledgeBaseRepository(session)
        self.doc_repo = DocumentRepository(session)
        self.img_repo = ImageRepository(session)

    async def _get_or_404(
        self, user_id: uuid.UUID, kb_id: uuid.UUID
    ) -> KnowledgeBase:
        kb = await self.repo.get(user_id, kb_id)
        if not kb:
            raise BizError("知识库不存在", code=3040, status_code=404)
        return kb

    async def list_kbs(self, user_id: uuid.UUID) -> list[dict]:
        """列出全部知识库（含文档/图片实时计数）。确保默认库存在。"""
        await self.repo.ensure_default(user_id)
        kbs = await self.repo.list_by_user(user_id)
        counts = await self.repo.counts(user_id)
        out: list[dict] = []
        for kb in kbs:
            c = counts.get(kb.id, {})
            out.append(self._to_out(kb, c.get("doc_count", 0), c.get("image_count", 0)))
        return out

    async def create(
        self, user_id: uuid.UUID, body: KnowledgeBaseCreate
    ) -> dict:
        kb = KnowledgeBase(
            user_id=user_id,
            name=body.name.strip(),
            description=body.description,
            icon=body.icon or "📁",
            color=body.color or "#155EEF",
            is_default=False,
        )
        await self.repo.create(kb)
        logger.info("创建知识库: user=%s id=%s name=%s", user_id, kb.id, kb.name)
        return self._to_out(kb, 0, 0)

    async def update(
        self, user_id: uuid.UUID, kb_id: uuid.UUID, body: KnowledgeBaseUpdate
    ) -> dict:
        kb = await self._get_or_404(user_id, kb_id)
        if body.name is not None:
            kb.name = body.name.strip()
        if body.description is not None:
            kb.description = body.description
        if body.icon is not None:
            kb.icon = body.icon
        if body.color is not None:
            kb.color = body.color
        await self.repo.save(kb)
        counts = (await self.repo.counts(user_id)).get(kb.id, {})
        return self._to_out(
            kb, counts.get("doc_count", 0), counts.get("image_count", 0)
        )

    async def set_chat_enabled(
        self, user_id: uuid.UUID, kb_id: uuid.UUID, enabled: bool
    ) -> dict:
        """设置某知识库是否参与对话检索。"""
        kb = await self._get_or_404(user_id, kb_id)
        kb.chat_enabled = enabled
        await self.repo.save(kb)
        counts = (await self.repo.counts(user_id)).get(kb.id, {})
        return self._to_out(
            kb, counts.get("doc_count", 0), counts.get("image_count", 0)
        )

    async def get_detail(self, user_id: uuid.UUID, kb_id: uuid.UUID) -> dict:
        kb = await self._get_or_404(user_id, kb_id)
        counts = (await self.repo.counts(user_id)).get(kb.id, {})
        return self._to_out(
            kb, counts.get("doc_count", 0), counts.get("image_count", 0)
        )

    async def delete(self, user_id: uuid.UUID, kb_id: uuid.UUID) -> None:
        """物理删除知识库及其全部文档/图片（ES chunk + OSS 文件 + PG 级联）。"""
        kb = await self._get_or_404(user_id, kb_id)
        if kb.is_default:
            raise BizError("默认知识库不可删除", code=3041, status_code=400)

        # 1. 清理库内文档/图片的 ES chunk + OSS 文件（DB 记录靠外键 CASCADE 删）
        docs = await self.doc_repo.list_by_kb(user_id, kb_id)
        imgs = await self.img_repo.list_by_kb(user_id, kb_id)
        storage = get_storage()
        for d in docs:
            try:
                await delete_by_source(str(user_id), str(d.id))
                await storage.delete(d.file_key)
            except Exception as e:
                logger.warning("删库清理文档失败（跳过 %s）: %s", d.id, e)
        for im in imgs:
            try:
                await delete_by_source(str(user_id), str(im.id))
                await storage.delete(im.file_key)
            except Exception as e:
                logger.warning("删库清理图片失败（跳过 %s）: %s", im.id, e)

        # 2. 删库（外键 ondelete=CASCADE 级联删除 documents/images PG 记录）
        await self.repo.delete(kb)
        logger.info(
            "删除知识库: user=%s id=%s docs=%d imgs=%d",
            user_id,
            kb_id,
            len(docs),
            len(imgs),
        )

    @staticmethod
    def _to_out(kb: KnowledgeBase, doc_count: int, image_count: int) -> dict:
        return {
            "id": str(kb.id),
            "name": kb.name,
            "description": kb.description,
            "icon": kb.icon,
            "color": kb.color,
            "is_default": kb.is_default,
            "chat_enabled": kb.chat_enabled,
            "doc_count": doc_count,
            "image_count": image_count,
            "created_at": kb.created_at.isoformat() if kb.created_at else None,
        }


__all__ = ["KnowledgeBaseService"]
