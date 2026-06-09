"""图片相关 Pydantic 模型。"""
import uuid
from datetime import datetime

from pydantic import BaseModel


class ImageOut(BaseModel):
    id: uuid.UUID
    file_name: str
    file_ext: str
    file_size: int
    url: str
    description: str | None
    objects: list | None
    scene: str | None
    status: str
    error_msg: str | None
    created_at: datetime


class ImageListData(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[ImageOut]
