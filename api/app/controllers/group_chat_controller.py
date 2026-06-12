"""群聊路由：建群 + 群成员信息 + SSE 流式群聊。

群聊复用 conversations / messages（is_group / member_persona_ids / sender_persona_id），
会话列表、消息列表、删除/改名沿用 chat_controller 的会话接口。
"""
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.response import success
from app.db.postgres import get_session
from app.models.user_model import User
from app.schemas.group_chat_schema import GroupChatStreamRequest, GroupCreateRequest
from app.services.conversation_service import ConversationService
from app.services.group_chat_service import GroupChatService

router = APIRouter(tags=["group-chat"])


@router.post("/groups")
async def create_group(
    body: GroupCreateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """新建群聊会话（勾选 2~5 个角色卡 + 群名）。"""
    service = GroupChatService(session)
    conv = await service.create_group(user.id, body)
    return success(ConversationService(session).to_out_dict(conv), "已创建群聊")


@router.get("/groups/{conv_id}/members")
async def list_group_members(
    conv_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """获取群成员（角色卡 id/名字/头像），供前端按发送者展示。"""
    service = GroupChatService(session)
    members = await service.list_members(user.id, conv_id)
    return success(members)


@router.post("/groups/chat/stream")
async def group_chat_stream(
    body: GroupChatStreamRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """群聊流式：主持人调度多角色依次发言。"""
    service = GroupChatService(session)
    return StreamingResponse(
        service.stream_group_chat(user.id, body),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
