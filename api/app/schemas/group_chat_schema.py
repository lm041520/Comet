"""群聊相关请求 schema。"""
import uuid

from pydantic import BaseModel, Field


class GroupCreateRequest(BaseModel):
    """新建群聊：勾选 2~5 个角色卡 + 可选群名 + 是否开启工具（默认关）。"""

    title: str | None = Field(default=None, max_length=256)
    member_persona_ids: list[uuid.UUID] = Field(..., min_length=2, max_length=5)
    enable_tools: bool = False


class GroupChatStreamRequest(BaseModel):
    """群聊发送消息（SSE 流式）。消息含 @角色名 时只让被 @ 的角色回复。"""

    conversation_id: uuid.UUID
    message: str = Field(..., min_length=1)
