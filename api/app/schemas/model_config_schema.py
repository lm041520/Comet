"""模型配置相关 Pydantic 模型。"""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ModelTypeT = Literal["chat", "multimodal", "embedding"]
ProviderT = Literal["openai", "qwen", "doubao", "deepseek"]


class ModelConfigCreate(BaseModel):
    type: ModelTypeT
    provider: ProviderT
    name: str = Field(min_length=1, max_length=128)
    model_name: str = Field(min_length=1, max_length=128)
    api_key: str = Field(min_length=1)
    base_url: str = Field(min_length=1, max_length=255)
    capability: list[str] = Field(default_factory=list)
    is_default: bool = False


class ModelConfigUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    model_name: str | None = Field(default=None, max_length=128)
    # 留空表示不修改 key；传新值则更新
    api_key: str | None = None
    base_url: str | None = Field(default=None, max_length=255)
    capability: list[str] | None = None


class ModelConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    provider: str
    name: str
    model_name: str
    api_key_masked: str  # 掩码，不返回明文
    base_url: str
    capability: list[str]
    is_default: bool
    created_at: datetime


class ConnectionTestResult(BaseModel):
    success: bool
    message: str
