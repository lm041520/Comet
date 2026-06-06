"""记忆路由：主动记住 / 列表 / 详情 / 删除。

检索接口在第③步随记忆检索一起加入。
"""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.response import success
from app.db.postgres import get_session
from app.models.user_model import User
from app.schemas.memory_schema import MemorySearchRequest, RememberRequest
from app.services.memory_service import MemoryService

router = APIRouter(prefix="/memories", tags=["memory"])


@router.post("/remember")
async def remember(
    body: RememberRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = MemoryService(session)
    memory = await service.remember(user.id, body.text)
    return success(service.to_out_dict(memory), "已提交，正在萃取记忆")


@router.post("/search")
async def search_memory(
    body: MemorySearchRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    hits = await MemoryService(session).search(user.id, body.query, body.top_k)
    return success(hits)


@router.get("/profile")
async def get_profile(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """画像视图：系统记住的实体（按类型分组）+ 类型计数。"""
    data = await MemoryService(session).get_profile(user.id)
    return success(data)


@router.delete("/entity/{entity_id}")
async def delete_entity(
    entity_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """删除单个记忆实体（连带其关系）。"""
    await MemoryService(session).delete_entity(user.id, entity_id)
    return success(message="删除成功")


@router.get("/communities")
async def list_communities(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """社区列表（名称/摘要/成员数）。"""
    return success(await MemoryService(session).list_communities(user.id))


@router.get("/communities/{community_id}")
async def community_members(
    community_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """某社区的成员实体。"""
    return success(await MemoryService(session).community_members(user.id, community_id))


@router.post("/recluster")
async def recluster(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """手动触发全量社区聚类。"""
    await MemoryService(session).recluster(user.id)
    return success(message="聚类完成")


@router.post("/merge-duplicates")
async def merge_duplicates(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """合并历史重复实体（同名同类型只保留一个图节点）。"""
    removed = await MemoryService(session).merge_duplicates(user.id)
    return success({"removed": removed}, f"已合并 {removed} 个重复实体")


@router.post("/consolidate")
async def consolidate(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """手动触发记忆巩固（短期记忆→长期 + 核心实体画像增强）。"""
    stats = await MemoryService(session).consolidate(user.id)
    return success(stats, "记忆巩固完成")


@router.get("/graph")
async def get_graph(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """知识图谱全量数据：实体节点 + 关系边 + 社区。"""
    return success(await MemoryService(session).get_graph(user.id))


@router.get("/graph/entity/{entity_id}")
async def get_entity_subgraph(
    entity_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """单实体一跳邻居子图。"""
    return success(await MemoryService(session).get_entity_subgraph(user.id, entity_id))


@router.get("/timeline")
async def get_timeline(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """事件时间线（按事件时间倒序）。"""
    return success(await MemoryService(session).get_timeline(user.id))


@router.get("")
async def list_memories(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = MemoryService(session)
    items, total = await service.list_memories(user.id, page, page_size)
    return success(
        {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [service.to_out_dict(m) for m in items],
        }
    )


@router.get("/{memory_id}")
async def get_memory(
    memory_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = MemoryService(session)
    memory = await service.get_detail(user.id, memory_id)
    return success(service.to_out_dict(memory))


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await MemoryService(session).delete(user.id, memory_id)
    return success(message="删除成功")
