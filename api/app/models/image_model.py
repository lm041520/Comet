"""Image ORM 模型 —— PostgreSQL images 表（图片元数据）。

原始图片存对象存储（file_key），多模态模型生成的描述向量进 ES，可被搜索。
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base

IMG_STATUS_PENDING = "pending"
IMG_STATUS_PROCESSING = "processing"
IMG_STATUS_DONE = "done"
IMG_STATUS_FAILED = "failed"


class Image(Base):
    __tablename__ = "images"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    file_name: Mapped[str] = mapped_column(String(512))
    file_ext: Mapped[str] = mapped_column(String(16))
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    file_key: Mapped[str] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)  # AI 详细描述
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # 图中文字
    objects: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # 物体列表
    scene: Mapped[str | None] = mapped_column(String(256), nullable=True)  # 场景
    status: Mapped[str] = mapped_column(
        String(16), default=IMG_STATUS_PENDING, index=True
    )
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
