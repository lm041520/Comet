"""记忆巩固引擎：短期→长期提升 + 核心实体画像增强。

提升规则（满足任一，只升不降）：
- access_count >= consolidate_min_access（被检索复用）
- importance >= consolidate_min_importance（本身重要）
- mention_count >= consolidate_min_mention 且存在满 consolidate_min_age_hours 小时

画像增强：对 top-K 高频长期实体，用 LLM 汇总其关联陈述 → 回写 core_facts/traits。
"""
from datetime import datetime, timedelta

from app.config import settings
from app.core.llm.client import LLMClient
from app.core.logging import get_logger
from app.core.memory.json_utils import parse_json_object
from app.core.memory.prompt_renderer import render_prompt
from app.repositories.neo4j.memory_graph_repository import MemoryGraphRepository

logger = get_logger(__name__)


def _coerce_str_list(value, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value[:limit]:
        s = str(item).strip()
        if s:
            out.append(s[:200])
    return out


class ConsolidationEngine:
    """记忆巩固：短期→长期 + 画像增强。chat_client 可选（无则跳过画像增强）。"""

    def __init__(self, chat_client: LLMClient | None = None):
        self.repo = MemoryGraphRepository()
        self.chat_client = chat_client

    async def run(self, user_id: str) -> dict:
        """对单个用户执行一次巩固。返回统计。"""
        now = datetime.now()
        age_before = (now - timedelta(hours=settings.consolidate_min_age_hours)).isoformat()

        ent_cnt, stmt_cnt = await self.repo.promote_short_to_long(
            user_id,
            min_access=settings.consolidate_min_access,
            min_importance=settings.consolidate_min_importance,
            min_mention=settings.consolidate_min_mention,
            age_before=age_before,
        )

        enhanced = 0
        if self.chat_client is not None:
            enhanced = await self._enhance_profiles(user_id)

        stats = {"promoted_entities": ent_cnt, "promoted_statements": stmt_cnt,
                 "enhanced_profiles": enhanced}
        logger.info("记忆巩固完成: user=%s %s", user_id, stats)
        return stats

    async def _enhance_profiles(self, user_id: str) -> int:
        """对 top-K 高频长期实体做画像增强。单个失败跳过。"""
        tops = await self.repo.top_long_term_entities(
            user_id, settings.consolidate_profile_top_k
        )
        enhanced = 0
        for ent in tops:
            try:
                statements = await self.repo.entity_statements(user_id, ent["id"])
                if len(statements) < 2:
                    continue  # 陈述太少，无需汇总
                core_facts, traits = await self._summarize(
                    ent.get("name", ""), ent.get("type", ""), statements
                )
                if core_facts or traits:
                    await self.repo.write_entity_profile(
                        user_id, ent["id"], core_facts, traits
                    )
                    enhanced += 1
            except Exception as e:
                logger.warning("画像增强失败（跳过实体 %s）: %s", ent.get("id"), e)
        return enhanced

    async def _summarize(
        self, name: str, type_: str, statements: list[str]
    ) -> tuple[list[str], list[str]]:
        """调 LLM 汇总核心事实与特质。"""
        prompt = render_prompt(
            "enhance_profile.jinja2",
            entity_name=name, entity_type=type_, statements=statements[:50],
        )
        answer = await self.chat_client.chat(
            [{"role": "user", "content": prompt}], temperature=0.3, max_tokens=600
        )
        data = parse_json_object(answer)
        return (
            _coerce_str_list(data.get("core_facts"), 8),
            _coerce_str_list(data.get("traits"), 8),
        )


__all__ = ["ConsolidationEngine"]
