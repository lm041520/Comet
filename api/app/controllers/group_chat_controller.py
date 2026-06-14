"""群聊路由：建群 + 群成员信息 + SSE 流式群聊。

群聊复用 conversations / messages（is_group / member_persona_ids / sender_persona_id），
会话列表、消息列表、删除/改名沿用 chat_controller 的会话接口。
"""
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.response import success
from app.db.postgres import get_session
from app.models.user_model import User
from app.schemas.group_chat_schema import (
    GroupChatStreamRequest,
    GroupCreateRequest,
    GroupJoinRequest,
    GroupSayRequest,
    GroupToolsRequest,
)
from app.services.conversation_service import ConversationService
from app.services.group_chat_service import GroupChatService

router = APIRouter(tags=["group-chat"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


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


@router.delete("/groups/{conv_id}/messages")
async def clear_group_messages(
    conv_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """清空群聊会话的所有消息（保留会话本身和成员配置）。"""
    service = GroupChatService(session)
    # 先校验群聊存在且属于当前用户
    await service.get_group_or_404(user.id, conv_id)
    from app.repositories.conversation_repository import MessageRepository
    msg_repo = MessageRepository(session)
    await msg_repo.delete_by_conversation(conv_id)
    return success(None, "消息已清空")


# ── 多人实时群聊：邀请 / 加入 / 成员 / 发言 / 事件订阅 ──


@router.get("/groups")
async def list_my_groups(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """我的群聊列表：自建的 + 凭码加入的。"""
    service = GroupChatService(session)
    convs = await service.list_my_groups(user.id)
    out = []
    for c in convs:
        d = ConversationService(session).to_out_dict(c)
        d["is_owner"] = c.user_id == user.id
        d["avatar_members"] = await service.avatar_members(c)
        out.append(d)
    return success(out)


@router.post("/groups/{conv_id}/invite")
async def get_group_invite(
    conv_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """群主获取邀请码（无则生成）。前端据此拼邀请链接。"""
    service = GroupChatService(session)
    code = await service.get_or_create_join_code(user.id, conv_id)
    return success({"join_code": code})


@router.post("/groups/{conv_id}/invite/reset")
async def reset_group_invite(
    conv_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """群主重置邀请码（旧码失效）。"""
    service = GroupChatService(session)
    code = await service.reset_join_code(user.id, conv_id)
    return success({"join_code": code}, "邀请码已重置")


@router.patch("/groups/{conv_id}/tools")
async def set_group_tools(
    conv_id: uuid.UUID,
    body: GroupToolsRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """群主开/关本群工具（知识库/记忆/联网/MCP）。下一轮 AI 发言即按新值生效。"""
    service = GroupChatService(session)
    enabled = await service.set_tools(user.id, conv_id, body.enabled)
    return success({"enable_tools": enabled}, "已更新")


@router.post("/groups/join")
async def join_group(
    body: GroupJoinRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """凭邀请码加入群聊。"""
    service = GroupChatService(session)
    conv = await service.join_by_code(user.id, body.code, body.nickname)
    return success(ConversationService(session).to_out_dict(conv), "已加入群聊")


@router.post("/groups/{conv_id}/leave")
async def leave_group(
    conv_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """退出群聊（群主不可退）。"""
    service = GroupChatService(session)
    await service.leave_group(user.id, conv_id)
    return success(None, "已退出群聊")


@router.get("/groups/{conv_id}/humans")
async def list_group_humans(
    conv_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """群里的真人成员列表。"""
    service = GroupChatService(session)
    humans = await service.list_humans(user.id, conv_id)
    return success(humans)


@router.get("/groups/{conv_id}/messages")
async def list_group_messages(
    conv_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """群聊历史消息（成员可读，区分真人发送者与 AI 角色）。"""
    service = GroupChatService(session)
    msgs = await service.list_group_messages(user.id, conv_id)
    return success(msgs)


@router.get("/groups/{conv_id}/members/{member_user_id}/avatar")
async def get_group_member_avatar(
    conv_id: uuid.UUID,
    member_user_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """读取群内某成员的头像（同群成员之间可见）。"""
    service = GroupChatService(session)
    content, mime = await service.get_member_avatar(user.id, conv_id, member_user_id)
    return Response(content=content, media_type=mime)


@router.post("/groups/{conv_id}/say")
async def group_say(
    conv_id: uuid.UUID,
    body: GroupSayRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """多人实时群聊发言：落库 + 广播 + 后台触发 AI 接话，立即返回。"""
    service = GroupChatService(session)
    result = await service.say(user.id, conv_id, body)
    return success(result)


@router.get("/groups/{conv_id}/events")
async def group_events(
    conv_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """SSE 订阅：实时接收全员发言与 AI 接话事件。"""
    service = GroupChatService(session)
    return StreamingResponse(
        service.events(user.id, conv_id),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
