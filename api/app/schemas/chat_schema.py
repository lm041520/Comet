"""对话相关请求/响应 schema。"""
import uuid

from pydantic import BaseModel, Field


class ConversationCreateRequest(BaseModel):
    title: str = Field(default="新对话", max_length=256)


class ConversationRenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=256)


class ChatAttachment(BaseModel):
    """对话临时附件：解析后的文档文本，仅服务本次对话，不进知识库。"""

    file_name: str = Field(..., max_length=256)
    text: str = Field(default="")


class ChatStreamRequest(BaseModel):
    """发送消息（SSE 流式）。conversation_id 为空则自动新建会话。"""

    conversation_id: uuid.UUID | None = None
    message: str = Field(..., min_length=1)
    # 多模态：图片 file_key 列表（阶段5 第③步接入）
    image_keys: list[str] = Field(default_factory=list)
    # 对话临时附件（文档文本），仅本次对话上下文使用，不入库
    attachments: list[ChatAttachment] = Field(default_factory=list)
    # 本轮工具开关（覆盖 agent 默认），None 表示用 agent 配置默认
    enable_knowledge: bool | None = None
    enable_memory: bool | None = None
    enable_web_search: bool | None = None


class FeedbackRequest(BaseModel):
    """对 AI 回复的赞/踩反馈。"""

    rating: str = Field(..., pattern="^(up|down)$")
    comment: str | None = Field(default=None, max_length=1000)
