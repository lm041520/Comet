"""仪表盘统计业务服务：聚合 PG / Neo4j 计数与分布，供首页与记忆统计展示。"""
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.conversation_model import Conversation
from app.models.document_model import Document
from app.models.image_model import Image
from app.models.memory_model import Memory
from app.models.tag_model import Tag, document_tags

logger = get_logger(__name__)


class DashboardService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _count(self, model, user_id: uuid.UUID) -> int:
        total = await self.session.scalar(
            select(func.count()).select_from(model).where(model.user_id == user_id)
        )
        return int(total or 0)

    async def _entity_community_counts(self, user_id: str) -> tuple[int, int]:
        """从 Neo4j 取实体数与社区数。失败返回 0,0。"""
        try:
            from app.repositories.neo4j.community_repository import CommunityRepository
            from app.repositories.neo4j.memory_graph_repository import (
                MemoryGraphRepository,
            )

            entity_cnt = await MemoryGraphRepository().count_entities(user_id)
            communities = await CommunityRepository().list_communities(user_id)
            return entity_cnt, len(communities)
        except Exception as e:
            logger.warning("仪表盘取图谱计数失败: %s", e)
            return 0, 0

    async def overview(self, user_id: uuid.UUID) -> dict:
        """概览统计：各类计数 + 知识库标签分布 + 最近活动。"""
        doc_cnt = await self._count(Document, user_id)
        img_cnt = await self._count(Image, user_id)
        conv_cnt = await self._count(Conversation, user_id)
        entity_cnt, community_cnt = await self._entity_community_counts(str(user_id))

        # 标签分布（文档维度，取 top 10）
        tag_rows = await self.session.execute(
            select(Tag.name, func.count(document_tags.c.document_id))
            .join(document_tags, Tag.id == document_tags.c.tag_id)
            .where(Tag.user_id == user_id)
            .group_by(Tag.name)
            .order_by(func.count(document_tags.c.document_id).desc())
            .limit(10)
        )
        tag_distribution = [{"name": n, "value": c} for n, c in tag_rows.all()]

        # 最近活动：最近 5 个文档 + 最近 5 条主动记住
        recent_docs = await self.session.execute(
            select(Document.file_name, Document.created_at)
            .where(Document.user_id == user_id)
            .order_by(Document.created_at.desc())
            .limit(5)
        )
        recent = [
            {"type": "document", "title": name, "time": t.isoformat() if t else None}
            for name, t in recent_docs.all()
        ]

        return {
            "counts": {
                "documents": doc_cnt,
                "images": img_cnt,
                "conversations": conv_cnt,
                "entities": entity_cnt,
                "communities": community_cnt,
            },
            "tag_distribution": tag_distribution,
            "recent": recent,
        }

    async def memory_stats(self, user_id: uuid.UUID) -> dict:
        """记忆统计：近 14 天记忆新增趋势 + 社区分布。"""
        today = datetime.now().date()
        start = today - timedelta(days=13)

        # 近 14 天每天的 memories 新增数（来源不限）
        rows = await self.session.execute(
            select(
                func.date(Memory.created_at).label("d"),
                func.count().label("cnt"),
            )
            .where(Memory.user_id == user_id, Memory.created_at >= start)
            .group_by(func.date(Memory.created_at))
        )
        day_map = {str(r.d): r.cnt for r in rows.all()}
        trend = [
            {
                "date": (start + timedelta(days=i)).isoformat(),
                "count": int(day_map.get((start + timedelta(days=i)).isoformat(), 0)),
            }
            for i in range(14)
        ]

        # 社区分布（成员数）
        community_dist: list[dict] = []
        try:
            from app.repositories.neo4j.community_repository import CommunityRepository

            communities = await CommunityRepository().list_communities(str(user_id))
            community_dist = [
                {"name": c["name"], "value": c["member_count"]} for c in communities[:10]
            ]
        except Exception as e:
            logger.warning("仪表盘取社区分布失败: %s", e)

        return {"trend": trend, "community_distribution": community_dist}

    async def agent_briefing(self, user_id: uuid.UUID, limit: int = 5) -> list[dict]:
        """Agent 简报:最近完成的深度研究报告(含定时任务产出),供首页主动呈现。"""
        from app.models.research_report_model import (
            RESEARCH_STATUS_DONE,
            ResearchReport,
        )

        rows = await self.session.execute(
            select(
                ResearchReport.id,
                ResearchReport.title,
                ResearchReport.topic,
                ResearchReport.task_id,
                ResearchReport.created_at,
            )
            .where(
                ResearchReport.user_id == user_id,
                ResearchReport.status == RESEARCH_STATUS_DONE,
            )
            .order_by(ResearchReport.created_at.desc())
            .limit(limit)
        )
        return [
            {
                "id": str(rid),
                "title": title or topic,
                "scheduled": task_id is not None,
                "created_at": t.isoformat() if t else None,
            }
            for rid, title, topic, task_id, t in rows.all()
        ]

    async def loop_health(self, user_id: uuid.UUID, days: int = 30) -> dict:
        """V0.0.5 ② Loop 健康度:近 N 天 Verifier Loop 运行情况聚合。

        返回:
        - total / passed / exceeded / failed:状态分布
        - one_shot_pass_rate:一次通过率(iterations=1 且 status=passed)
        - avg_iterations:平均迭代次数(passed + exceeded)
        - avg_final_score:平均最终评分(passed + exceeded)
        - failure_dims:失败维度归因(各维度单维不达硬门槛的次数 top 5)
        - verifier_kinds:verifier_kind 分布(same / cross 各跑了多少次)
        """
        from datetime import datetime as _dt, timedelta

        from app.models.loop_model import (
            STATUS_EXCEEDED,
            STATUS_FAILED,
            STATUS_PASSED,
            LoopIteration,
            LoopRun,
        )

        # loop_runs.started_at 是 TIMESTAMP WITHOUT TIME ZONE（naive），
        # 用 naive now() 保持一致，避免 aware/naive 混用触发 asyncpg DataError
        since = _dt.now() - timedelta(days=days)

        # 1) 状态分布 + 迭代/评分平均(passed/exceeded 计入)
        rows = await self.session.execute(
            select(LoopRun.status, LoopRun.iterations, LoopRun.final_score,
                   LoopRun.verifier_kind)
            .where(LoopRun.user_id == user_id)
            .where(LoopRun.started_at >= since)
        )
        runs = rows.all()
        total = len(runs)
        passed = sum(1 for r in runs if r.status == STATUS_PASSED)
        exceeded = sum(1 for r in runs if r.status == STATUS_EXCEEDED)
        failed = sum(1 for r in runs if r.status == STATUS_FAILED)
        # 一次通过率:第一轮就通过的占比(passed 且 iterations=1)
        one_shot = sum(1 for r in runs if r.status == STATUS_PASSED and r.iterations == 1)
        one_shot_rate = round(one_shot / total, 4) if total else 0.0
        # 平均迭代(只看 passed/exceeded,failed 是异常崩溃没意义)
        valid_for_avg = [r for r in runs if r.status in (STATUS_PASSED, STATUS_EXCEEDED)]
        avg_iter = (
            round(sum(r.iterations for r in valid_for_avg) / len(valid_for_avg), 2)
            if valid_for_avg else 0.0
        )
        scores = [r.final_score for r in valid_for_avg if r.final_score is not None]
        avg_score = round(sum(scores) / len(scores), 4) if scores else 0.0
        # verifier_kind 分布
        kind_dist: dict[str, int] = {}
        for r in runs:
            k = r.verifier_kind or "(none)"
            kind_dist[k] = kind_dist.get(k, 0) + 1

        # 2) 失败维度归因:扫所有 iterations,统计各维度单维不达硬门槛的次数
        # 硬门槛与 rubric/research.py 保持一致(变了顺手在这里同步)
        thresholds = {
            "coverage": 3.0,
            "faithfulness": 3.0,
            "depth": 2.0,
            "timeliness": 3.0,
            "relevance": 3.0,
            "readability": 2.0,
        }
        labels = {
            "coverage": "覆盖度",
            "faithfulness": "引用对齐",
            "depth": "论证深度",
            "timeliness": "时效性",
            "relevance": "相关性",
            "readability": "结构与可读",
        }
        # 只拉本用户近 N 天的 iterations(走 JOIN 避免拉全表)
        it_rows = await self.session.execute(
            select(LoopIteration.scores)
            .join(LoopRun, LoopIteration.run_id == LoopRun.id)
            .where(LoopRun.user_id == user_id)
            .where(LoopRun.started_at >= since)
        )
        dim_fail_count: dict[str, int] = {}
        for (scores_jsonb,) in it_rows.all():
            raw = (scores_jsonb or {}).get("raw") or {}
            for dim, thr in thresholds.items():
                v = raw.get(dim)
                if isinstance(v, (int, float)) and float(v) < thr:
                    dim_fail_count[dim] = dim_fail_count.get(dim, 0) + 1
        failure_dims = sorted(
            [{"dim": d, "label": labels.get(d, d), "count": c}
             for d, c in dim_fail_count.items()],
            key=lambda x: x["count"], reverse=True,
        )[:6]

        return {
            "days": days,
            "total": total,
            "passed": passed,
            "exceeded": exceeded,
            "failed": failed,
            "one_shot_pass_rate": one_shot_rate,
            "avg_iterations": avg_iter,
            "avg_final_score": avg_score,
            "failure_dims": failure_dims,
            "verifier_kinds": kind_dist,
        }


__all__ = ["DashboardService"]
