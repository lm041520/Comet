"""文档数据访问层。所有查询强制带 user_id 隔离。"""
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document_model import Document
from app.models.tag_model import Tag, document_tags


class DocumentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, doc: Document) -> Document:
        self.session.add(doc)
        await self.session.commit()
        await self.session.refresh(doc)
        return doc

    async def get(
        self, user_id: uuid.UUID, doc_id: uuid.UUID
    ) -> Document | None:
        stmt = select(Document).where(
            Document.id == doc_id, Document.user_id == user_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, doc_id: uuid.UUID) -> Document | None:
        return await self.session.get(Document, doc_id)

    async def list_paged(
        self,
        user_id: uuid.UUID,
        page: int,
        page_size: int,
        tag: str | None = None,
        kb_id: uuid.UUID | None = None,
    ) -> tuple[list[Document], int]:
        base = select(Document).where(Document.user_id == user_id)
        if kb_id:
            base = base.where(Document.kb_id == kb_id)
        if tag:
            # 按标签名过滤：join 关联表 + tags 表
            base = (
                base.join(document_tags, Document.id == document_tags.c.document_id)
                .join(Tag, Tag.id == document_tags.c.tag_id)
                .where(Tag.user_id == user_id, Tag.name == tag)
            )
        total = await self.session.scalar(
            select(func.count()).select_from(base.subquery())
        )
        stmt = (
            base.order_by(Document.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), int(total or 0)

    async def list_by_kb(
        self, user_id: uuid.UUID, kb_id: uuid.UUID
    ) -> list[Document]:
        """取某知识库下全部文档（删库级联清理用）。"""
        stmt = select(Document).where(
            Document.user_id == user_id, Document.kb_id == kb_id
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_many(
        self,
        user_id: uuid.UUID,
        document_ids: list[uuid.UUID],
        kb_id: uuid.UUID | None = None,
    ) -> list[Document]:
        if not document_ids:
            return []
        stmt = select(Document).where(
            Document.id.in_(document_ids),
            Document.user_id == user_id,
        )
        if kb_id is not None:
            stmt = stmt.where(Document.kb_id == kb_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def save(self, doc: Document) -> Document:
        await self.session.commit()
        await self.session.refresh(doc)
        return doc

    async def delete(self, doc: Document) -> None:
        await self.session.delete(doc)
        await self.session.commit()
