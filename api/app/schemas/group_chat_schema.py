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
    # 多模态：图片 file_key 列表（带图时每个角色用多模态模型看图发言）
    image_keys: list[str] = Field(default_factory=list)


class GroupSayRequest(BaseModel):
    """多人实时群聊：某真人成员发言。落库后广播，后台触发 AI 接话。"""

    message: str = Field(..., min_length=1)
    image_keys: list[str] = Field(default_factory=list)


class GroupJoinRequest(BaseModel):
    """凭邀请码加入群聊。"""

    code: str = Field(..., min_length=1, max_length=16)
    nickname: str | None = Field(default=None, max_length=64)


class GroupToolsRequest(BaseModel):
    """群主开/关本群工具（知识库/记忆/联网/MCP）。"""

    enabled: bool

