"""技能（Skill）请求/响应 schema。"""
from pydantic import BaseModel, Field


class FewShot(BaseModel):
    """few-shot 示例：输入 → 理想输出。"""

    input: str = Field(default="", max_length=2000)
    output: str = Field(default="", max_length=4000)


class SkillConfig(BaseModel):
    """技能轻量配置（存 config JSONB）。"""

    quick_prompts: list[str] = Field(default_factory=list)
    few_shots: list[FewShot] = Field(default_factory=list)


class SkillCreate(BaseModel):
    """新增技能。name 必填，其余可选。"""

    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=256)
    icon: str = Field(default="🧩", max_length=16)
    prompt: str = Field(default="", max_length=8000)
    tool_keys: list[str] = Field(default_factory=list)
    kb_id: str | None = Field(default=None)
    enabled: bool = Field(default=True)
    config: SkillConfig = Field(default_factory=SkillConfig)


class SkillUpdate(BaseModel):
    """编辑技能（全部可选，传啥改啥）。kb_id 传空串/None 表示解绑。"""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=256)
    icon: str | None = Field(default=None, max_length=16)
    prompt: str | None = Field(default=None, max_length=8000)
    tool_keys: list[str] | None = Field(default=None)
    kb_id: str | None = Field(default=None)
    enabled: bool | None = Field(default=None)
    config: SkillConfig | None = Field(default=None)


class SkillOut(BaseModel):
    """技能出参。"""

    id: str
    name: str
    description: str
    icon: str
    prompt: str
    tool_keys: list[str]
    kb_id: str | None
    enabled: bool
    config: dict
    is_builtin: bool


class BuiltinSkillOut(BaseModel):
    """内置技能模板出参（用于「一键添加」前的展示）。"""

    key: str
    name: str
    description: str
    icon: str
    prompt: str
    tool_keys: list[str]
    config: dict


class OptimizeSkillPromptRequest(BaseModel):
    """技能任务提示词一键优化请求。"""

    prompt: str = Field(default="", max_length=8000)
