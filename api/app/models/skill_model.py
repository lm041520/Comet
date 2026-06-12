"""Skill ORM 模型 —— 技能（任务能力包）。

比角色卡更聚焦的「专项任务」配置：专属提示词 + 限定工具白名单 + 可选绑定知识库
+ 轻量配置（快捷开场提问 / few-shot 示例）。对话中可临时挂载/切换，与角色卡叠加生效。

字段说明：
- prompt: 该技能的专属任务提示词，与角色卡 system_prompt 叠加注入。
- tool_keys: 工具白名单（内置工具 key 列表）。非空=只启用这些工具；空=不限定（用全局配置）。
- kb_id: 可选绑定的知识库；绑了则该技能的知识库检索限定到此库（优先于对话页选的库集合）。
- config: 轻量 JSON 配置，含 quick_prompts（快捷开场提问列表）/ few_shots（输入→输出示例）。
- is_builtin: 是否内置模板复制而来（保留标记，便于前端区分；用户可改可删）。
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    # 技能名（如「论文精读」「代码审查」）
    name: Mapped[str] = mapped_column(String(64))
    # 简介（一句话说明用途）
    description: Mapped[str] = mapped_column(String(256), default="")
    # 图标（emoji）
    icon: Mapped[str] = mapped_column(String(16), default="🧩")
    # 专属任务提示词，对话时与角色卡 system_prompt 叠加注入
    prompt: Mapped[str] = mapped_column(Text, default="")
    # 工具白名单：内置工具 key 列表。非空=只用这些；空列表=不限定（用全局工具配置）
    tool_keys: Mapped[list] = mapped_column(JSONB, default=list)
    # 可选绑定知识库（删库则置空），绑了优先用此库做检索范围
    kb_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # 轻量配置：{ quick_prompts: [str], few_shots: [{input, output}] }
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    # 是否在对话页技能选择器中显示（关闭则不占用对话框入口，避免技能多时拥挤）
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # 是否由内置模板复制而来（标记用途，用户仍可改删）
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    # 列表排序
    sort: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
