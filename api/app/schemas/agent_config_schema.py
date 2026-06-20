"""Agent 配置请求/响应 schema。"""
from pydantic import BaseModel, Field


class AgentConfigUpdate(BaseModel):
    """更新 Agent 配置（全部可选，传啥改啥）。"""

    system_prompt: str | None = Field(default=None, max_length=4000)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    enable_knowledge: bool | None = None
    enable_memory: bool | None = None
    enable_web_search: bool | None = None
    enable_active_recall: bool | None = None
    enable_cross_session: bool | None = None
    show_avatar: bool | None = None
    human_mode: bool | None = None


class OptimizePromptRequest(BaseModel):
    """提示词优化入参。"""

    system_prompt: str = Field(min_length=1, max_length=4000)


class OptimizePromptResult(BaseModel):
    """提示词优化结果。"""

    optimized: str
