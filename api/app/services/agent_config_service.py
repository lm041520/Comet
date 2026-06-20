"""Agent 配置业务服务：取/更新用户的 Agent 个性化配置（每用户一条，懒创建）。"""
import uuid

from langchain_core.messages import HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent.prompt_renderer import render_agent_prompt
from app.core.exceptions import BizError
from app.core.llm.chat_model import build_default_chat_model
from app.core.logging import get_logger
from app.models.agent_config_model import AgentConfig
from app.repositories.agent_config_repository import AgentConfigRepository
from app.schemas.agent_config_schema import AgentConfigUpdate

logger = get_logger(__name__)


class AgentConfigService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = AgentConfigRepository(session)

    async def get_or_create(self, user_id: uuid.UUID) -> AgentConfig:
        config = await self.repo.get_by_user(user_id)
        if config is None:
            config = await self.repo.create(AgentConfig(user_id=user_id))
        return config

    async def update(
        self, user_id: uuid.UUID, body: AgentConfigUpdate
    ) -> AgentConfig:
        config = await self.get_or_create(user_id)
        if body.system_prompt is not None:
            config.system_prompt = body.system_prompt
        if body.temperature is not None:
            config.temperature = body.temperature
        if body.enable_knowledge is not None:
            config.enable_knowledge = body.enable_knowledge
        if body.enable_memory is not None:
            config.enable_memory = body.enable_memory
        if body.enable_web_search is not None:
            config.enable_web_search = body.enable_web_search
        if body.enable_active_recall is not None:
            config.enable_active_recall = body.enable_active_recall
        if body.enable_cross_session is not None:
            config.enable_cross_session = body.enable_cross_session
        if body.show_avatar is not None:
            config.show_avatar = body.show_avatar
        if body.human_mode is not None:
            config.human_mode = body.human_mode
        return await self.repo.save(config)

    async def optimize_prompt(self, user_id: uuid.UUID, raw_prompt: str) -> str:
        """调用默认对话模型，按元提示词把用户的 system_prompt 改写得更专业。"""
        raw = (raw_prompt or "").strip()
        if not raw:
            raise BizError("请先填写要优化的提示词", code=4060)
        model, _ = await build_default_chat_model(
            self.session, user_id, temperature=0.4, streaming=False
        )
        meta_prompt = render_agent_prompt("optimize_prompt.jinja2", raw_prompt=raw)
        try:
            resp = await model.ainvoke([HumanMessage(content=meta_prompt)])
        except Exception as e:
            logger.warning("提示词优化失败: user=%s err=%s", user_id, e)
            raise BizError(f"优化失败：{e}", code=4061) from e
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        optimized = self._strip_code_fence(content.strip())
        if not optimized:
            raise BizError("优化未返回有效内容", code=4062)
        logger.info("提示词优化成功: user=%s in=%d out=%d", user_id, len(raw), len(optimized))
        return optimized

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        """兜底剥离 LLM 可能误加的 ``` 代码块包裹（prompt 已要求不包裹，模型未必遵守）。"""
        t = text.strip()
        if t.startswith("```"):
            # 去掉首行 ```或```lang，以及结尾的 ```
            lines = t.splitlines()
            if lines:
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            t = "\n".join(lines).strip()
        return t

    @staticmethod
    def to_out_dict(config: AgentConfig) -> dict:
        return {
            "system_prompt": config.system_prompt,
            "temperature": config.temperature,
            "enable_knowledge": config.enable_knowledge,
            "enable_memory": config.enable_memory,
            "enable_web_search": config.enable_web_search,
            "enable_active_recall": config.enable_active_recall,
            "enable_cross_session": config.enable_cross_session,
            "show_avatar": config.show_avatar,
            "human_mode": config.human_mode,
        }
