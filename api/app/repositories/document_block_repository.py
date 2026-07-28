"""DocumentBlock 数据访问层。"""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rag.ingestion.models import DocumentBlock as ParsedBlock
from app.models.document_block_model import DocumentBlock
from app.models.document_model import Document


class DocumentBlockRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def replace_for_document(
        self,
        document_id: uuid.UUID,
        blocks: list[ParsedBlock],
    ) -> list[DocumentBlock]:
        """原子替换某文档的全部 Block，供解析重试保持幂等。"""
        await self.session.execute(
            delete(DocumentBlock).where(DocumentBlock.document_id == document_id)
        )
        models = [
            DocumentBlock(
                id=uuid.UUID(block.block_id),
                document_id=document_id,
                block_order=block.order,
                block_type=block.block_type.value,
                content=block.content,
                page_start=block.page_start,
                page_end=block.page_end,
                heading_path=block.heading_path,
                extra_json=block.metadata,
            )
            for block in blocks
        ]
        self.session.add_all(models)
        await self.session.commit()
        return models

    async def list_for_document(
        self,
        user_id: uuid.UUID,
        document_id: uuid.UUID,
    ) -> list[DocumentBlock]:
        stmt = (
            select(DocumentBlock)
            .join(Document, Document.id == DocumentBlock.document_id)
            .where(
                DocumentBlock.document_id == document_id,
                Document.user_id == user_id,
            )
            .order_by(DocumentBlock.block_order)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_many(
        self,
        user_id: uuid.UUID,
        block_ids: list[uuid.UUID],
        kb_id: uuid.UUID | None = None,
    ) -> list[DocumentBlock]:
        if not block_ids:
            return []
        stmt = (
            select(DocumentBlock)
            .join(Document, Document.id == DocumentBlock.document_id)
            .where(
                DocumentBlock.id.in_(block_ids),
                Document.user_id == user_id,
            )
            .order_by(DocumentBlock.block_order)
        )
        if kb_id is not None:
            stmt = stmt.where(Document.kb_id == kb_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
