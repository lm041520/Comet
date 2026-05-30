"""标签业务服务：列表/重命名改色/合并/删除。"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError
from app.repositories.tag_repository import TagRepository


class TagService:
    def __init__(self, session: AsyncSession):
        self.repo = TagRepository(session)

    async def list_tags(
        self, user_id: uuid.UUID, scope: str = "all"
    ) -> list[dict]:
        tags = await self.repo.list_by_scope(user_id, scope)
        result = []
        for t in tags:
            if scope == "image":
                count = await self.repo.count_images(t.id)
            elif scope == "document":
                count = await self.repo.count_documents(t.id)
            else:
                count = await self.repo.count_documents(
                    t.id
                ) + await self.repo.count_images(t.id)
            result.append(
                {
                    "id": str(t.id),
                    "name": t.name,
                    "color": t.color,
                    "doc_count": count,
                }
            )
        return result

    async def _get_or_404(self, user_id: uuid.UUID, tag_id: uuid.UUID):
        tag = await self.repo.get(user_id, tag_id)
        if not tag:
            raise BizError("标签不存在", code=3010, status_code=404)
        return tag

    async def update(
        self,
        user_id: uuid.UUID,
        tag_id: uuid.UUID,
        name: str | None,
        color: str | None,
    ) -> dict:
        tag = await self._get_or_404(user_id, tag_id)
        if name is not None:
            tag.name = name
        if color is not None:
            tag.color = color
        await self.repo.save(tag)
        return {"id": str(tag.id), "name": tag.name, "color": tag.color}

    async def merge(
        self, user_id: uuid.UUID, source_id: uuid.UUID, target_id: uuid.UUID
    ) -> None:
        if source_id == target_id:
            raise BizError("不能合并到自身", code=3011)
        await self._get_or_404(user_id, source_id)
        await self._get_or_404(user_id, target_id)
        await self.repo.merge(source_id, target_id)

    async def delete(self, user_id: uuid.UUID, tag_id: uuid.UUID) -> None:
        tag = await self._get_or_404(user_id, tag_id)
        await self.repo.delete_tag(tag)
