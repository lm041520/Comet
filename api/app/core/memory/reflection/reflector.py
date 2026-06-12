"""反思引擎：回看高频/高重要度实体与代表性陈述，LLM 归纳高层洞察 Insight。

产出按 theme 收敛（同主题 upsert，不重复堆叠）；洞察向量化便于 ③ 主动召回按话题检索。
遵循「记忆不遗忘」：只新增/更新高层洞察节点，不删改原子记忆。
"""
from app.config import settings
from app.core.llm.client import LLMClient
from app.core.logging import get_logger
from app.core.memory.extraction.embedder import embed_texts
from app.core.memory.json_utils import parse_json_object
from app.core.memory.prompt_renderer import render_prompt
from app.repositories.neo4j.memory_graph_repository import MemoryGraphRepository

logger = get_logger(__name__)


class ReflectionEngine:
    """反思引擎。chat_client 必需（归纳洞察）；embed_client 可选（无则洞察不带向量）。"""

    def __init__(
        self,
        chat_client: LLMClient | None = None,
        embed_client: LLMClient | None = None,
    ):
        self.repo = MemoryGraphRepository()
        self.chat_client = chat_client
        self.embed_client = embed_client

    async def run(self, user_id: str) -> dict:
        """对单个用户执行一次反思。返回统计。"""
        if self.chat_client is None:
            logger.info("跳过反思（未配置 chat 模型）: user=%s", user_id)
            return {"insights": 0, "skipped": "no_chat_model"}

        entities = await self.repo.reflection_top_entities(
            user_id, settings.reflection_top_k
        )
        if len(entities) < settings.reflection_min_entities:
            logger.info(
                "跳过反思（实体太少 %d<%d）: user=%s",
                len(entities), settings.reflection_min_entities, user_id,
            )
            return {"insights": 0, "skipped": "too_few_entities"}

        # 组装记忆清单：实体 + 类型 + 画像 + 代表性陈述
        memory_block, name_to_id = await self._build_memory_block(user_id, entities)

        # LLM 归纳
        prompt = render_prompt(
            "reflect.jinja2",
            memory_block=memory_block,
            min_insights=settings.reflection_min_insights,
            max_insights=settings.reflection_max_insights,
        )
        try:
            answer = await self.chat_client.chat(
                [{"role": "user", "content": prompt}], temperature=0.5, max_tokens=2048
            )
        except Exception as e:
            logger.warning("反思 LLM 调用失败: user=%s err=%s", user_id, e)
            return {"insights": 0, "error": str(e)}

        data = parse_json_object(answer)
        raw_insights = data.get("insights") if isinstance(data, dict) else None
        if not isinstance(raw_insights, list) or not raw_insights:
            logger.info("反思未产出洞察: user=%s", user_id)
            return {"insights": 0}

        # 向量化洞察内容（便于 ③ 按话题召回）
        contents = [
            str(it.get("content", "")).strip()
            for it in raw_insights
            if isinstance(it, dict) and str(it.get("content", "")).strip()
        ]
        embeddings: list = []
        if self.embed_client is not None and contents:
            embeddings = await embed_texts(self.embed_client, contents)

        # 落库（按 theme upsert）
        saved = 0
        emb_idx = 0
        for it in raw_insights:
            if not isinstance(it, dict):
                continue
            theme = str(it.get("theme", "")).strip()
            content = str(it.get("content", "")).strip()
            if not theme or not content:
                continue
            # 安全兜底：洞察应是一句概括，超长则截断，避免异常长文/截断残句入库
            if len(content) > 200:
                content = content[:200].rstrip() + "…"
            embedding = None
            if embeddings and emb_idx < len(embeddings):
                embedding = embeddings[emb_idx]
            emb_idx += 1
            based_on = it.get("based_on") or []
            entity_ids = [
                name_to_id[str(n).strip()]
                for n in based_on
                if str(n).strip() in name_to_id
            ]
            try:
                await self.repo.upsert_insight(
                    user_id=user_id,
                    theme=theme,
                    content=content,
                    embedding=embedding,
                    importance=_clamp(it.get("importance"), 0.6),
                    confidence=_clamp(it.get("confidence"), 0.7),
                    source_count=len(entity_ids),
                    entity_ids=entity_ids,
                )
                saved += 1
            except Exception as e:
                logger.warning("洞察落库失败（跳过 theme=%s）: %s", theme, e)

        logger.info("反思完成: user=%s 产出洞察=%d", user_id, saved)
        return {"insights": saved}

    async def _build_memory_block(
        self, user_id: str, entities: list[dict]
    ) -> tuple[str, dict[str, str]]:
        """把实体与代表性陈述拼成可读的记忆清单文本，并返回 名称→id 映射。"""
        lines: list[str] = []
        name_to_id: dict[str, str] = {}
        for e in entities:
            name = (e.get("name") or "").strip()
            if not name:
                continue
            name_to_id[name] = e.get("id")
            type_ = e.get("type") or ""
            desc = (e.get("description") or "").strip()
            traits = e.get("traits") or []
            core_facts = e.get("core_facts") or []
            header = f"- 【{type_}】{name}"
            if desc:
                header += f"：{desc}"
            lines.append(header)
            if core_facts:
                lines.append(f"    核心事实：{'；'.join(str(f) for f in core_facts[:5])}")
            if traits:
                lines.append(f"    特质：{'、'.join(str(t) for t in traits[:5])}")
            stmts = await self.repo.reflection_entity_statements(
                user_id, e.get("id"), settings.reflection_stmt_per_entity
            )
            for s in stmts:
                lines.append(f"    · {s}")
        return "\n".join(lines), name_to_id


def _clamp(value, default: float) -> float:
    """把 LLM 给的分数夹到 [0,1]，非法用默认。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, v))


__all__ = ["ReflectionEngine"]
