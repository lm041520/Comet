"""Celery 应用：标准多队列配置（不做自研调度器）。

队列规划：
- parse    文档解析 / 图片描述
- memory   记忆三元组萃取 / 去重
- beat     社区聚类 / 每日回顾（由 beat 定时触发）
"""
from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "comet",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.tasks",
        "app.tasks.parse",
        "app.tasks.image",
        "app.tasks.memory",
        "app.tasks.emotion",
        "app.tasks.beat",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=False,
    task_track_started=True,
    task_default_queue="default",
    task_routes={
        "app.tasks.parse.*": {"queue": "parse"},
        "app.tasks.image.*": {"queue": "parse"},
        "app.tasks.memory.*": {"queue": "memory"},
        "app.tasks.emotion.*": {"queue": "memory"},
        "app.tasks.beat.*": {"queue": "beat"},
    },
    # Celery beat 定时
    beat_schedule={
        "daily-review": {
            "task": "app.tasks.beat.generate_daily_reviews",
            "schedule": crontab(hour=22, minute=0),  # 每天 22:00 生成回顾
        },
        "cluster-communities": {
            "task": "app.tasks.beat.cluster_communities",
            "schedule": crontab(hour=3, minute=0),  # 每天凌晨 3:00 全量聚类兜底
        },
        "consolidate-memory": {
            "task": "app.tasks.beat.consolidate_memory",
            "schedule": crontab(hour=4, minute=0),  # 每天凌晨 4:00 记忆巩固
        },
    },
)
