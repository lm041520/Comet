"""标签数据访问层。"""
import random
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tag_model import Tag, document_tags, image_tags

# 标签随机配色（参考主题色系，柔和好看）
_TAG_COLORS = [
    "#155EEF",  # 蓝
    "#369F21",  # 绿
    "#FF5D34",  # 橙红
    "#7839EE",  # 紫
    "#E62E89",  # 玫红
    "#0E9384",  # 青
    "#DD2590",  # 粉
    "#EF6820",  # 橙
    "#4E5BA6",  # 靛
    "#B54708",  # 棕
]


def random_tag_color() -> str:
    return random.choice(_TAG_COLORS)


class TagRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create(self, user_id: uuid.UUID, name: str) -> Tag:
        stmt = select(Tag).where(Tag.user_id == user_id, Tag.name == name)
        tag = (await self.session.execute(stmt)).scalar_one_or_none()
        if tag:
            return tag
        tag = Tag(user_id=user_id, name=name, color=random_tag_color())
        self.session.add(tag)
        await self.session.commit()
        await self.session.refresh(tag)
        return tag

    async def list_by_user(self, user_id: uuid.UUID) -> list[Tag]:
        stmt = select(Tag).where(Tag.user_id == user_id).order_by(Tag.name)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get(self, user_id: uuid.UUID, tag_id: uuid.UUID) -> Tag | None:
        stmt = select(Tag).where(Tag.id == tag_id, Tag.user_id == user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def count_documents(self, tag_id: uuid.UUID) -> int:
        stmt = select(func.count()).where(document_tags.c.tag_id == tag_id)
        return int(await self.session.scalar(stmt) or 0)

    async def count_images(self, tag_id: uuid.UUID) -> int:
        stmt = select(func.count()).where(image_tags.c.tag_id == tag_id)
        return int(await self.session.scalar(stmt) or 0)

    async def list_by_scope(self, user_id: uuid.UUID, scope: str) -> list[Tag]:
        """按使用范围列标签：document=有文档关联的，image=有图片关联的，all=全部。"""
        if scope == "document":
            stmt = (
                select(Tag)
                .join(document_tags, Tag.id == document_tags.c.tag_id)
                .where(Tag.user_id == user_id)
                .distinct()
                .order_by(Tag.name)
            )
        elif scope == "image":
            stmt = (
                select(Tag)
                .join(image_tags, Tag.id == image_tags.c.tag_id)
                .where(Tag.user_id == user_id)
                .distinct()
                .order_by(Tag.name)
            )
        else:
            stmt = select(Tag).where(Tag.user_id == user_id).order_by(Tag.name)
        return list((await self.session.execute(stmt)).scalars().all())

    async def set_document_tags(
        self, document_id: uuid.UUID, tag_ids: list[uuid.UUID]
    ) -> None:
        await self.session.execute(
            delete(document_tags).where(document_tags.c.document_id == document_id)
        )
        for tid in tag_ids:
            await self.session.execute(
                document_tags.insert().values(document_id=document_id, tag_id=tid)
            )
        await self.session.commit()

    async def get_document_tag_names(self, document_id: uuid.UUID) -> list[str]:
        stmt = (
            select(Tag.name)
            .join(document_tags, Tag.id == document_tags.c.tag_id)
            .where(document_tags.c.document_id == document_id)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_document_tags(self, document_id: uuid.UUID) -> list[dict]:
        """返回文档标签的 name + color，供前端按颜色渲染。"""
        stmt = (
            select(Tag.name, Tag.color)
            .join(document_tags, Tag.id == document_tags.c.tag_id)
            .where(document_tags.c.document_id == document_id)
        )
        rows = (await self.session.execute(stmt)).all()
        return [{"name": r.name, "color": r.color} for r in rows]

    async def set_image_tags(
        self, image_id: uuid.UUID, tag_ids: list[uuid.UUID]
    ) -> None:
        await self.session.execute(
            delete(image_tags).where(image_tags.c.image_id == image_id)
        )
        for tid in tag_ids:
            await self.session.execute(
                image_tags.insert().values(image_id=image_id, tag_id=tid)
            )
        await self.session.commit()

    async def get_image_tags(self, image_id: uuid.UUID) -> list[dict]:
        stmt = (
            select(Tag.name, Tag.color)
            .join(image_tags, Tag.id == image_tags.c.tag_id)
            .where(image_tags.c.image_id == image_id)
        )
        rows = (await self.session.execute(stmt)).all()
        return [{"name": r.name, "color": r.color} for r in rows]

    async def save(self, tag: Tag) -> Tag:
        await self.session.commit()
        await self.session.refresh(tag)
        return tag

    async def delete_tag(self, tag: Tag) -> None:
        await self.session.delete(tag)
        await self.session.commit()

    async def merge(self, source_id: uuid.UUID, target_id: uuid.UUID) -> None:
        """把 source 标签的文档/图片关联迁到 target，再删除 source。"""
        # 文档关联迁移（避免重复主键：先删 target 已有的，再改 source 的）
        await self.session.execute(
            document_tags.delete().where(
                document_tags.c.tag_id == source_id,
                document_tags.c.document_id.in_(
                    select(document_tags.c.document_id).where(
                        document_tags.c.tag_id == target_id
                    )
                ),
            )
        )
        await self.session.execute(
            document_tags.update()
            .where(document_tags.c.tag_id == source_id)
            .values(tag_id=target_id)
        )
        # 图片关联迁移
        await self.session.execute(
            image_tags.delete().where(
                image_tags.c.tag_id == source_id,
                image_tags.c.image_id.in_(
                    select(image_tags.c.image_id).where(
                        image_tags.c.tag_id == target_id
                    )
                ),
            )
        )
        await self.session.execute(
            image_tags.update()
            .where(image_tags.c.tag_id == source_id)
            .values(tag_id=target_id)
        )
        # 删除 source 标签
        src = await self.session.get(Tag, source_id)
        if src:
            await self.session.delete(src)
        await self.session.commit()
