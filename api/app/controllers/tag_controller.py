"""标签路由：列表 / 重命名改色 / 合并 / 删除。"""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.response import success
from app.db.postgres import get_session
from app.models.user_model import User
from app.schemas.tag_schema import TagMergeRequest, TagUpdate
from app.services.tag_service import TagService

router = APIRouter(prefix="/tags", tags=["tag"])


@router.get("")
async def list_tags(
    scope: str = Query(default="all", description="范围: all/document/image"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return success(await TagService(session).list_tags(user.id, scope))


@router.put("/{tag_id}")
async def update_tag(
    tag_id: uuid.UUID,
    body: TagUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    data = await TagService(session).update(user.id, tag_id, body.name, body.color)
    return success(data, "更新成功")


@router.post("/merge")
async def merge_tags(
    body: TagMergeRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await TagService(session).merge(user.id, body.source_id, body.target_id)
    return success(message="合并成功")


@router.delete("/{tag_id}")
async def delete_tag(
    tag_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await TagService(session).delete(user.id, tag_id)
    return success(message="删除成功")
