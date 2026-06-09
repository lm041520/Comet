"""图片数据访问层。所有查询强制带 user_id 隔离。"""
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.image_model import Image
from app.models.tag_model import Tag, image_tags


class ImageRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, image: Image) -> Image:
        self.session.add(image)
        await self.session.commit()
        await self.session.refresh(image)
        return image

    async def get(self, user_id: uuid.UUID, image_id: uuid.UUID) -> Image | None:
        stmt = select(Image).where(Image.id == image_id, Image.user_id == user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_id(self, image_id: uuid.UUID) -> Image | None:
        return await self.session.get(Image, image_id)

    async def get_by_file_key(
        self, user_id: uuid.UUID, file_key: str
    ) -> Image | None:
        stmt = select(Image).where(
            Image.user_id == user_id, Image.file_key == file_key
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_paged(
        self,
        user_id: uuid.UUID,
        page: int,
        page_size: int,
        tag: str | None = None,
    ) -> tuple[list[Image], int]:
        base = select(Image).where(Image.user_id == user_id)
        if tag:
            base = (
                base.join(image_tags, Image.id == image_tags.c.image_id)
                .join(Tag, Tag.id == image_tags.c.tag_id)
                .where(Tag.user_id == user_id, Tag.name == tag)
            )
        total = await self.session.scalar(
            select(func.count()).select_from(base.subquery())
        )
        stmt = (
            base.order_by(Image.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), int(total or 0)

    async def save(self, image: Image) -> Image:
        await self.session.commit()
        await self.session.refresh(image)
        return image

    async def delete(self, image: Image) -> None:
        await self.session.delete(image)
        await self.session.commit()
