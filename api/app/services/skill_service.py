"""技能（Skill）业务服务：CRUD + 一键添加内置模板。

技能是「任务能力包」：专属提示词 + 工具白名单 + 可选绑定知识库 + 快捷提问/few-shot，
对话中临时挂载，与角色卡叠加生效。
"""
# 延迟注解求值：本类有名为 list 的方法，会遮蔽内置 list，
# 使后续 `-> list[dict]` 注解在类体执行时报错；用 future 注解规避。
from __future__ import annotations

import uuid

from langchain_core.messages import HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent.prompt_renderer import render_agent_prompt
from app.core.exceptions import BizError
from app.core.llm.chat_model import build_default_chat_model
from app.core.logging import get_logger
from app.models.skill_model import Skill
from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.repositories.skill_repository import SkillRepository
from app.schemas.skill_schema import SkillConfig, SkillCreate, SkillUpdate
from app.services.skill_builtins import BUILTIN_SKILLS, get_builtin_skill

logger = get_logger(__name__)

# 单用户技能数量上限，防滥用
MAX_SKILLS = 100


class SkillService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = SkillRepository(session)

    async def list(self, user_id: uuid.UUID) -> list[Skill]:
        return await self.repo.list_by_user(user_id)

    async def _get_or_404(self, user_id: uuid.UUID, skill_id: uuid.UUID) -> Skill:
        skill = await self.repo.get(user_id, skill_id)
        if skill is None:
            raise BizError("技能不存在", code=4050, status_code=404)
        return skill

    async def _validate_kb(
        self, user_id: uuid.UUID, kb_id: str | None
    ) -> uuid.UUID | None:
        """校验知识库归属；空串/None 表示不绑定。"""
        if not kb_id:
            return None
        try:
            kb_uuid = uuid.UUID(str(kb_id))
        except (ValueError, TypeError) as e:
            raise BizError("知识库 id 非法", code=4051) from e
        kb = await KnowledgeBaseRepository(self.session).get(user_id, kb_uuid)
        if kb is None:
            raise BizError("绑定的知识库不存在", code=4052, status_code=404)
        return kb_uuid

    async def create(self, user_id: uuid.UUID, body: SkillCreate) -> Skill:
        if await self.repo.count(user_id) >= MAX_SKILLS:
            raise BizError(f"技能数量已达上限（{MAX_SKILLS}）", code=4053)
        kb_uuid = await self._validate_kb(user_id, body.kb_id)
        skill = Skill(
            user_id=user_id,
            name=body.name.strip(),
            description=body.description or "",
            icon=body.icon or "🧩",
            prompt=body.prompt or "",
            tool_keys=body.tool_keys or [],
            kb_id=kb_uuid,
            enabled=body.enabled,
            config=body.config.model_dump(),
        )
        created = await self.repo.add(skill)
        logger.info("创建技能: user=%s skill=%s name=%s", user_id, created.id, created.name)
        return created

    async def update(
        self, user_id: uuid.UUID, skill_id: uuid.UUID, body: SkillUpdate
    ) -> Skill:
        skill = await self._get_or_404(user_id, skill_id)
        fields = body.model_dump(exclude_unset=True)
        if "name" in fields and fields["name"] is not None:
            skill.name = fields["name"].strip()
        if "description" in fields and fields["description"] is not None:
            skill.description = fields["description"]
        if "icon" in fields and fields["icon"] is not None:
            skill.icon = fields["icon"]
        if "prompt" in fields and fields["prompt"] is not None:
            skill.prompt = fields["prompt"]
        if "tool_keys" in fields and fields["tool_keys"] is not None:
            skill.tool_keys = fields["tool_keys"]
        if "kb_id" in fields:
            skill.kb_id = await self._validate_kb(user_id, fields["kb_id"])
        if "enabled" in fields and fields["enabled"] is not None:
            skill.enabled = fields["enabled"]
        if "config" in fields and fields["config"] is not None:
            # body.config 已是 SkillConfig；model_dump 后是 dict
            cfg = body.config
            skill.config = cfg.model_dump() if isinstance(cfg, SkillConfig) else cfg
        return await self.repo.save(skill)

    async def delete(self, user_id: uuid.UUID, skill_id: uuid.UUID) -> None:
        skill = await self._get_or_404(user_id, skill_id)
        await self.repo.delete(skill)
        logger.info("删除技能: user=%s skill=%s", user_id, skill_id)

    async def add_builtin(self, user_id: uuid.UUID, key: str) -> Skill:
        """把一个内置模板复制为用户自己的技能。"""
        tpl = get_builtin_skill(key)
        if tpl is None:
            raise BizError("内置技能模板不存在", code=4054, status_code=404)
        if await self.repo.count(user_id) >= MAX_SKILLS:
            raise BizError(f"技能数量已达上限（{MAX_SKILLS}）", code=4053)
        skill = Skill(
            user_id=user_id,
            name=tpl["name"],
            description=tpl.get("description", ""),
            icon=tpl.get("icon", "🧩"),
            prompt=tpl.get("prompt", ""),
            tool_keys=list(tpl.get("tool_keys", [])),
            kb_id=None,
            config=dict(tpl.get("config", {})),
            is_builtin=True,
        )
        created = await self.repo.add(skill)
        logger.info("添加内置技能: user=%s key=%s skill=%s", user_id, key, created.id)
        return created

    async def optimize_prompt(self, user_id: uuid.UUID, raw_prompt: str) -> str:
        """调用默认对话模型，用「技能专用」元提示词把任务提示词改写得更专业。

        与角色卡人设优化分开：技能优化聚焦任务目标/步骤/输出格式/边界，不写人设。
        """
        raw = (raw_prompt or "").strip()
        if not raw:
            raise BizError("请先填写要优化的提示词", code=4063)
        model, _ = await build_default_chat_model(
            self.session, user_id, temperature=0.4, streaming=False
        )
        meta_prompt = render_agent_prompt("optimize_skill_prompt.jinja2", raw_prompt=raw)
        try:
            resp = await model.ainvoke([HumanMessage(content=meta_prompt)])
        except Exception as e:
            logger.warning("技能提示词优化失败: user=%s err=%s", user_id, e)
            raise BizError(f"优化失败：{e}", code=4064) from e
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        optimized = self._strip_code_fence(content.strip())
        if not optimized:
            raise BizError("优化未返回有效内容", code=4065)
        logger.info(
            "技能提示词优化成功: user=%s in=%d out=%d", user_id, len(raw), len(optimized)
        )
        return optimized

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        """兜底剥离 LLM 可能误加的 ``` 代码块包裹。"""
        t = text.strip()
        if t.startswith("```"):
            lines = t.splitlines()
            if lines:
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            t = "\n".join(lines).strip()
        return t

    @staticmethod
    def list_builtins() -> list[dict]:
        """内置技能模板列表（供前端展示「一键添加」）。"""
        return [
            {
                "key": s["key"],
                "name": s["name"],
                "description": s.get("description", ""),
                "icon": s.get("icon", "🧩"),
                "prompt": s.get("prompt", ""),
                "tool_keys": list(s.get("tool_keys", [])),
                "config": dict(s.get("config", {})),
            }
            for s in BUILTIN_SKILLS
        ]

    @staticmethod
    def to_out_dict(skill: Skill) -> dict:
        return {
            "id": str(skill.id),
            "name": skill.name,
            "description": skill.description,
            "icon": skill.icon,
            "prompt": skill.prompt,
            "tool_keys": skill.tool_keys or [],
            "kb_id": str(skill.kb_id) if skill.kb_id else None,
            "enabled": skill.enabled,
            "config": skill.config or {},
            "is_builtin": skill.is_builtin,
        }
