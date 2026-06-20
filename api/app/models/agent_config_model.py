"""AgentConfig ORM 模型 —— 用户的 Agent 个性化配置。

每用户一条：自定义 system prompt（人设/风格）+ 问答参数 + 工具开关。
问答时按此注入 system message 与编排行为。
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class AgentConfig(Base):
    __tablename__ = "agent_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    # 自定义系统提示词（人设/风格），问答时作为 system message 注入
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    # 工具默认开关（联网搜索默认关，知识库/记忆默认开）
    enable_knowledge: Mapped[bool] = mapped_column(Boolean, default=True)
    enable_memory: Mapped[bool] = mapped_column(Boolean, default=True)
    enable_web_search: Mapped[bool] = mapped_column(Boolean, default=False)
    # 主动记忆：每轮提问自动召回相关记忆 + 洞察注入上下文（默认开）
    enable_active_recall: Mapped[bool] = mapped_column(Boolean, default=True)
    # 跨会话上下文：注入最近其他会话的摘要，让跨会话也能接着聊（默认关）
    enable_cross_session: Mapped[bool] = mapped_column(Boolean, default=False)
    # 对话界面是否显示头像（开 → AI 人格头像 + 用户头像；关 → 两边都不显示）
    show_avatar: Mapped[bool] = mapped_column(Boolean, default=False)
    # 真人对话模式（全局）：开启后单聊/群聊都像真人微信聊天（口语短句、可多气泡），关闭恢复助手风格
    human_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
