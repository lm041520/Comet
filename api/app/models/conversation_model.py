"""Conversation / Message ORM 模型 —— 对话会话与消息。

一个用户有多个会话（conversations），每个会话有多条消息（messages）。
消息的 meta_data 存引用来源、工具调用记录、token 用量等问答附加信息。
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base

# 消息角色
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_SYSTEM = "system"


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(256), default="新对话")
    # 是否群聊会话（多角色卡）。普通单聊为 false。
    is_group: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # 群成员角色卡 id 列表（仅 is_group=true 时有意义）。
    member_persona_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # 群聊是否允许成员调用工具（知识库/记忆/联网/MCP），全群统一，默认关。
    enable_tools: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | system
    content: Mapped[str] = mapped_column(Text)
    # 群聊中该消息由哪个角色卡发出（user 消息为空；单聊 assistant 也为空）。
    sender_persona_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # 附加信息：引用 citations / 工具调用 tool_calls / token usage / 图片等
    meta_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
