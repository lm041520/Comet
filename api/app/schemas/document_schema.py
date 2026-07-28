"""知识库文档相关 Pydantic 模型。"""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class UrlImportRequest(BaseModel):
    url: str = Field(min_length=1, max_length=1024)
    kb_id: uuid.UUID | None = Field(default=None, description="归属知识库")


class DocumentOut(BaseModel):
    id: uuid.UUID
    file_name: str
    file_ext: str
    file_size: int
    source_type: str
    source_url: str | None
    status: str
    progress: float
    chunk_num: int
    error_msg: str | None
    content_hash: str | None = None
    preferred_parser: str = "auto"
    parser_name: str | None = None
    parser_version: str | None = None
    parse_status: str | None = None
    parse_summary: dict[str, Any] = Field(default_factory=dict)
    parsed_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime


class DocumentListOut(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[DocumentOut]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    tags: list[str] | None = None
    kb_id: uuid.UUID | None = None


class SearchHit(BaseModel):
    chunk_id: str
    content: str
    doc_name: str | None
    source_id: str | None
    source_type: str | None
    score: float
    matched_content: str | None = None
    kb_id: str | None = None
    block_ids: list[str] = Field(default_factory=list)
    block_types: list[str] = Field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    heading_path: list[str] = Field(default_factory=list)
    parser_name: str | None = None


class RetrievalValidationRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    kb_id: uuid.UUID
    top_k: int = Field(default=8, ge=1, le=20)
