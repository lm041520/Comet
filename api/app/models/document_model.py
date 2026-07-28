"""Document ORM 模型 —— PostgreSQL documents 表（文档元数据）。

原始文件存对象存储（file_key），解析后的 chunk 向量进 ES，本表只存元数据与解析状态。
"""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base

# 解析状态
DOC_STATUS_PENDING = "pending"
DOC_STATUS_PARSING = "parsing"
DOC_STATUS_DONE = "done"
DOC_STATUS_FAILED = "failed"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # 所属知识库（多知识库分类）。删库时整库资料一并删除，故 CASCADE。
    kb_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    file_name: Mapped[str] = mapped_column(String(512))
    file_ext: Mapped[str] = mapped_column(String(16))
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    file_key: Mapped[str] = mapped_column(String(512))  # 对象存储中的 key
    source_type: Mapped[str] = mapped_column(String(16), default="file")  # file | url
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default=DOC_STATUS_PENDING, index=True
    )
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    chunk_num: Mapped[int] = mapped_column(Integer, default=0)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    preferred_parser: Mapped[str] = mapped_column(String(16), default="auto")
    parser_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    parse_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True, index=True
    )
    parse_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    parsed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
