"""每日回顾业务服务：汇总当日新增对话/记忆/文档，LLM 生成简报。

双触发：用户打开仪表盘时按需生成（当天没有则现生成）；Celery beat 每日定时批量生成。
"""
import asyncio
import uuid
from datetime import date, datetime, time

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dashboard.prompt_renderer import render_prompt
from app.core.logging import get_logger
from app.db.postgres import SessionLocal
from app.models.conversation_model import ROLE_USER, Conversation, Message
from app.models.daily_review_model import DailyReview
from app.models.document_model import Document
from app.models.memory_model import Memory
from app.models.play_history_model import PlayHistory

logger = get_logger(__name__)

# 后台重生成任务引用集合（防 GC 提前回收）+ 正在生成的 (user, day) 去重集合
_REVIEW_BG_TASKS: set = set()
_REVIEW_GENERATING: set = set()


class DailyReviewService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _day_range(self, day: date) -> tuple[datetime, datetime]:
        start = datetime.combine(day, time.min)
        end = datetime.combine(day, time.max)
        return start, end

    async def _collect(self, user_id: uuid.UUID, day: date) -> dict:
        """收集当日新增的对话提问 / 主动记住 / 文档。"""
        start, end = await self._day_range(day)

        # 用户提问消息：
        # - 单聊：本人会话里的 user 提问（单聊 user 消息不带 sender_user_id）；
        # - 群聊：只取「本人发言」（sender_user_id == 当前用户），把邀请进来的其他真人
        #   成员的发言排除掉，避免别人说的话算进自己的个人回顾（数据隔离）。
        msg_rows = await self.session.execute(
            select(Message.content)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.role == ROLE_USER,
                Message.created_at >= start,
                Message.created_at <= end,
                or_(
                    and_(
                        Conversation.user_id == user_id,
                        Conversation.is_group.isnot(True),
                    ),
                    Message.sender_user_id == user_id,
                ),
            )
            .limit(30)
        )
        messages = [r[0] for r in msg_rows.all()]

        mem_rows = await self.session.execute(
            select(Memory.raw_text).where(
                Memory.user_id == user_id,
                Memory.created_at >= start,
                Memory.created_at <= end,
            )
        )
        memories = [r[0] for r in mem_rows.all()]

        doc_rows = await self.session.execute(
            select(Document.file_name).where(
                Document.user_id == user_id,
                Document.created_at >= start,
                Document.created_at <= end,
            )
        )
        documents = [r[0] for r in doc_rows.all()]

        # 今天听的歌（去重歌名，保留顺序）
        song_rows = await self.session.execute(
            select(PlayHistory.title, PlayHistory.artist)
            .where(
                PlayHistory.user_id == user_id,
                PlayHistory.played_at >= start,
                PlayHistory.played_at <= end,
            )
            .order_by(PlayHistory.played_at.asc())
        )
        seen: set[str] = set()
        songs: list[str] = []
        for title, artist in song_rows.all():
            label = f"{title}（{artist}）" if artist else title
            if label not in seen:
                seen.add(label)
                songs.append(label)

        return {
            "messages": messages,
            "memories": memories,
            "documents": documents,
            "songs": songs,
        }

    async def _collect_mood(self, user_id: uuid.UUID) -> str:
        """取今天的情绪画像，转成给 LLM 的一句话描述；无数据返回空串。"""
        try:
            from app.services.emotion_service import EmotionService

            data = await EmotionService(self.session).trend(user_id, 1)
            points = data.get("points", [])
            if not points:
                return ""
            today = points[-1]
            if (today.get("count") or 0) <= 0:
                return ""
            v = today.get("avg_valence", 0.0)
            if v >= 0.3:
                tone = "整体偏积极愉悦"
            elif v <= -0.3:
                tone = "情绪略低落"
            else:
                tone = "情绪比较平稳"
            return f"{tone}（效价 {v:.2f}，共 {today.get('count')} 条情绪记录）"
        except Exception as e:
            logger.warning("收集每日心情失败（忽略）: %s", e)
            return ""

    async def _generate_content_and_care(
        self, user_id: uuid.UUID, data: dict
    ) -> tuple[str, str]:
        """生成回顾正文 + 关怀句。

        先用 session 串行取好 client / 情绪 / 洞察（session 非并发安全），
        再把两次纯 httpx 的 LLM 调用并行（gather），避免串行叠加导致仪表盘加载慢。
        """
        from app.core.llm.resolver import get_optional_client_for_type

        songs = data.get("songs", [])
        total = (
            len(data["messages"])
            + len(data["memories"])
            + len(data["documents"])
            + len(songs)
        )
        content_fallback = (
            "今天还没有新动态，休息一下也很好 🌿"
            if total == 0
            else (
                f"今天有 {len(data['messages'])} 次提问、"
                f"记住了 {len(data['memories'])} 件事、"
                f"新增了 {len(data['documents'])} 份文档、"
                f"听了 {len(songs)} 首歌。"
            )
        )
        if total == 0:
            return content_fallback, ""

        # 串行取 session 相关数据（不可并发共用 session）
        client = await get_optional_client_for_type(self.session, user_id, "chat")
        if not client:
            return content_fallback, ""
        mood = await self._collect_mood(user_id)
        insights = await self._collect_insights(user_id)

        # 两次 LLM 调用并行（纯 httpx，无 session 依赖）
        content, care = await asyncio.gather(
            self._call_content(client, data, mood, content_fallback),
            self._call_care(client, data, mood, insights),
        )
        return content, care

    async def _call_content(
        self, client, data: dict, mood: str, fallback: str
    ) -> str:
        """调用 LLM 生成回顾正文（带一次重试）。"""
        songs = data.get("songs", [])
        prompt = render_prompt(
            "daily_review.jinja2",
            messages="；".join(data["messages"][:20]) or "（无）",
            memories="；".join(data["memories"][:30]) or "（无）",
            documents="、".join(data["documents"]) or "（无）",
            song_count=len(songs),
            songs="、".join(songs[:20]) or "（无）",
            mood=mood or "（暂无情绪数据）",
        )
        for attempt in range(2):
            try:
                text = await client.chat(
                    [{"role": "user", "content": prompt}],
                    temperature=0.7, max_tokens=600,
                )
                if text and text.strip():
                    return text.strip()
                logger.warning("每日回顾生成内容为空（第 %d 次）", attempt + 1)
            except Exception as e:
                logger.warning("每日回顾生成失败（第 %d 次）: %s", attempt + 1, e)
            if attempt == 0:
                await asyncio.sleep(0.6)
        return fallback

    async def _call_care(
        self, client, data: dict, mood: str, insights: str
    ) -> str:
        """调用 LLM 生成关怀句。失败返回空串。"""
        try:
            recent = "；".join((data.get("messages") or [])[:5]) or "（无）"
            memories = "；".join((data.get("memories") or [])[:10]) or "（无）"
            prompt = render_prompt(
                "daily_care.jinja2",
                mood=mood or "（暂无情绪数据）",
                insights=insights or "（暂无）",
                memories=memories,
                recent=recent,
            )
            text = await client.chat(
                [{"role": "user", "content": prompt}], temperature=0.8, max_tokens=200
            )
            return (text or "").strip().strip('"「」') if text else ""
        except Exception as e:
            logger.warning("生成关怀句失败（忽略）: err=%s", e)
            return ""

    async def _collect_insights(self, user_id: uuid.UUID) -> str:
        """取「AI 眼中的你」高层洞察，拼成一句话；无则空串。"""
        try:
            from app.repositories.neo4j.memory_graph_repository import (
                MemoryGraphRepository,
            )

            rows = await MemoryGraphRepository().list_insights(str(user_id))
            contents = [
                (r.get("content") or "").strip() for r in rows[:3]
            ]
            return "；".join(c for c in contents if c)
        except Exception as e:
            logger.warning("收集洞察失败（忽略）: %s", e)
            return ""

    @staticmethod
    def _instant_content(data: dict) -> str:
        """即时（非 LLM）兜底简报：用统计数拼一句话，供首屏秒显，后台再补全 LLM 正文。"""
        songs = data.get("songs", [])
        total = (
            len(data["messages"])
            + len(data["memories"])
            + len(data["documents"])
            + len(songs)
        )
        if total == 0:
            return "今天还没有新动态，休息一下也很好 🌿"
        return (
            f"今天有 {len(data['messages'])} 次提问、"
            f"记住了 {len(data['memories'])} 件事、"
            f"新增了 {len(data['documents'])} 份文档、"
            f"听了 {len(songs)} 首歌。"
        )

    async def _upsert(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        day: date,
        content: str,
        care: str,
        stats: dict,
    ) -> DailyReview:
        """插入或更新当天回顾记录。"""
        existing = await session.scalar(
            select(DailyReview).where(
                DailyReview.user_id == user_id, DailyReview.review_date == day
            )
        )
        if existing:
            existing.content = content
            existing.care = care
            existing.stats = stats
            await session.commit()
            await session.refresh(existing)
            return existing
        review = DailyReview(
            user_id=user_id, review_date=day, content=content, care=care, stats=stats
        )
        session.add(review)
        await session.commit()
        await session.refresh(review)
        return review

    async def generate_now(
        self, user_id: uuid.UUID, day: date | None = None
    ) -> dict:
        """同步全量生成当天回顾（采集 + LLM 正文/关怀 + 落库）。

        供 Celery beat 批量生成与后台重生成任务调用——它们本就跑在独立任务里，可以等。
        """
        day = day or date.today()
        data = await self._collect(user_id, day)
        stats = {
            "messages": len(data["messages"]),
            "memories": len(data["memories"]),
            "documents": len(data["documents"]),
            "songs": len(data.get("songs", [])),
        }
        content, care = await self._generate_content_and_care(user_id, data)
        review = await self._upsert(self.session, user_id, day, content, care, stats)
        return self.to_out_dict(review)

    async def get_or_generate(self, user_id: uuid.UUID, day: date | None = None) -> dict:
        """仪表盘按需获取当天回顾（非阻塞）。

        - 已有非空回顾且当天活动统计未变 → 直接复用（毫秒级）。
        - 无活动（total=0）→ 即时兜底文案落库直接返回，不调 LLM。
        - 否则 → 先把「即时统计文案/旧回顾」秒回，派后台任务异步重生成完整正文，
          返回体带 generating=True，前端据此轮询拿最终结果。不再让首屏干等 LLM。
        """
        day = day or date.today()
        existing = await self.session.scalar(
            select(DailyReview).where(
                DailyReview.user_id == user_id, DailyReview.review_date == day
            )
        )
        data = await self._collect(user_id, day)
        stats = {
            "messages": len(data["messages"]),
            "memories": len(data["memories"]),
            "documents": len(data["documents"]),
            "songs": len(data.get("songs", [])),
        }
        total = sum(stats.values())

        # 已有非空回顾且活动数据无变化 → 复用
        if (
            existing
            and existing.content
            and existing.content.strip()
            and self._same_stats(existing.stats, stats)
        ):
            out = self.to_out_dict(existing)
            out["generating"] = False
            return out

        # 无活动：即时兜底，不调 LLM
        if total == 0:
            review = await self._upsert(
                self.session, user_id, day, self._instant_content(data), "", stats
            )
            out = self.to_out_dict(review)
            out["generating"] = False
            return out

        # 需要(重)生成：先秒回即时内容（无旧回顾时建即时兜底；有旧的则保留旧文案显示），
        # 再派后台任务异步生成完整正文。
        if existing and existing.content and existing.content.strip():
            base = existing
        else:
            base = await self._upsert(
                self.session, user_id, day, self._instant_content(data), "", stats
            )
        out = self.to_out_dict(base)

        key = (str(user_id), day.isoformat())
        if key not in _REVIEW_GENERATING:
            _REVIEW_GENERATING.add(key)
            task = asyncio.create_task(self._regenerate_bg(user_id, day))
            _REVIEW_BG_TASKS.add(task)
            task.add_done_callback(_REVIEW_BG_TASKS.discard)
        out["generating"] = True
        return out

    async def _regenerate_bg(self, user_id: uuid.UUID, day: date) -> None:
        """后台任务：用独立 session 全量重生成当天回顾。失败记日志，不影响首屏。"""
        key = (str(user_id), day.isoformat())
        try:
            async with SessionLocal() as session:
                await DailyReviewService(session).generate_now(user_id, day)
        except Exception as e:
            logger.error(
                "每日回顾后台生成失败: user=%s err=%s", user_id, e, exc_info=True
            )
        finally:
            _REVIEW_GENERATING.discard(key)

    @staticmethod
    def _same_stats(old: dict | None, new: dict) -> bool:
        old = old or {}
        return all(
            int(old.get(k, 0) or 0) == int(new.get(k, 0) or 0)
            for k in ("messages", "memories", "documents", "songs")
        )

    @staticmethod
    def to_out_dict(review: DailyReview) -> dict:
        return {
            "date": review.review_date.isoformat(),
            "content": review.content,
            "care": review.care or "",
            "stats": review.stats,
            "generating": False,
            "created_at": review.created_at.isoformat() if review.created_at else None,
        }


__all__ = ["DailyReviewService"]
