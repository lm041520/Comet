"""ModelConfig ORM 模型 —— PostgreSQL model_configs 表。

每用户可配置多个模型，按 type 分三类：chat / multimodal / embedding。
四个 provider（openai/qwen/doubao/deepseek）均走 OpenAI 兼容接口，差异在 base_url。
API Key 用 Fernet 加密存储（api_key_encrypted），接口返回掩码。
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class ModelConfig(Base):
    __tablename__ = "model_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # 模型类型：chat（对话）/ multimodal（多模态/图片理解）/ embedding（向量化）
    type: Mapped[str] = mapped_column(String(32), index=True)
    # 供应商：openai / qwen / doubao / deepseek
    provider: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))  # 配置显示名
    model_name: Mapped[str] = mapped_column(String(128))  # 实际模型名，如 gpt-4o
    api_key_encrypted: Mapped[str] = mapped_column(String(512))  # Fernet 密文
    base_url: Mapped[str] = mapped_column(String(255))
    # 能力标记，如 ["function_call", "vision"]，阶段5 强弱模型路由用
    capability: Mapped[list] = mapped_column(JSONB, default=list)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
