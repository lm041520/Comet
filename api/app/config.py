"""应用配置：全部从环境变量 / .env 读取，不硬编码。"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # 应用
    app_name: str = "Comet"
    app_env: str = "development"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    cors_origins: str = "http://localhost:5173"

    # 安全
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080  # 7 天（免频繁重登）
    refresh_token_expire_days: int = 30
    fernet_key: str = "change-me-fernet-key"

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "comet"
    postgres_password: str = "comet"
    postgres_db: str = "comet"
    # PG 连接池
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30  # 取连接超时（秒）
    db_pool_recycle: int = 1800  # 连接回收（秒），防被 DB 端断开
    db_pool_pre_ping: bool = True  # 取连接前 ping，剔除失效连接
    db_statement_timeout_ms: int = 60000  # 单条 SQL 超时（毫秒）

    # Elasticsearch
    es_host: str = "http://localhost:9200"
    es_username: str = ""
    es_password: str = ""
    es_max_retries: int = 3
    es_request_timeout: int = 30  # 秒
    es_max_connections: int = 25

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "cometneo4j"
    neo4j_max_pool_size: int = 50
    neo4j_connection_timeout: int = 30  # 秒

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    redis_max_connections: int = 50
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # 文件存储
    storage_backend: str = "local"  # local | oss
    storage_dir: str = "./storage"

    # 阿里云 OSS
    oss_endpoint: str = ""
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""
    oss_bucket_name: str = ""

    # 日志
    log_level: str = "INFO"  # DEBUG/INFO/WARNING/ERROR
    log_to_console: bool = True
    log_to_file: bool = True
    log_file_path: str = "./logs/comet.log"
    log_max_bytes: int = 10 * 1024 * 1024  # 单文件 10MB
    log_backup_count: int = 5  # 轮转保留份数
    db_echo: bool = False  # 是否打印 SQL（调试用，默认关，避免日志刷屏）

    # 知识库 RAG
    embedding_dims: int = 1024  # 向量维度，ES 索引与 embed 调用统一用此值

    # 全局搜索语义门控（精确导向）：只展示余弦相似度 ≥ 阈值的结果，没有就不展示
    # 阈值为真实余弦相似度（-1~1），按实测可调；偏高更精准、偏低召回更多
    global_search_min_vector_score: float = 0.45
    memory_search_min_vector_score: float = 0.45

    # 情绪记忆：对话后情绪分析强度阈值（低于此值的弱情绪丢弃，不入库）
    emotion_min_intensity: float = 0.15
    # 当前情绪画像聚合窗口：取最近 N 条情绪记录做平均
    emotion_profile_window: int = 20

    # 记忆巩固（短期→长期提升，只升不降）
    consolidate_min_access: int = 2  # 被检索复用次数达标即提升
    consolidate_min_importance: float = 0.7  # 重要度达标即提升
    consolidate_min_mention: int = 3  # 提及次数达标即提升
    consolidate_min_age_hours: int = 24  # 凭提及次数提升需存在满 N 小时
    consolidate_profile_top_k: int = 5  # 每次巩固对 top-K 高频实体做画像增强

    # 反思引擎（归纳高层洞察 Insight）
    reflection_top_k: int = 25  # 反思输入：top-N 高重要度/高频实体
    reflection_stmt_per_entity: int = 4  # 每个实体取几条代表性陈述
    reflection_min_insights: int = 3  # 期望产出洞察下限
    reflection_max_insights: int = 6  # 期望产出洞察上限
    reflection_min_entities: int = 5  # 实体少于此数不反思（信息太少）
    reflection_trigger_threshold: int = 20  # 增量触发：累计新增记忆达标触发一次反思

    # 记忆主动召回（对话每轮注入相关记忆 + 洞察）
    active_recall_entity_top_k: int = 5  # 召回实体数
    active_recall_insight_top_k: int = 2  # 召回洞察数
    active_recall_min_score: float = 0.5  # 实体召回余弦门控（低于不注入，节流防噪声）
    active_recall_min_confidence: float = 0.6  # 低于此置信度的记忆不进入回答侧主动召回
    active_recall_uncertain_confidence: float = 0.75  # 低于此置信度的记忆注入时标为待确认
    active_recall_max_chars: int = 600  # 注入背景块长度上限

    # 跨会话上下文（注入最近其他会话的摘要，默认关）
    cross_session_max_convs: int = 3  # 取最近几个其他会话
    cross_session_turns_per_conv: int = 4  # 每会话取最后几轮
    cross_session_max_chars: int = 1200  # 注入上限

    # 深度研究 → 报告（多步自主研究：规划 → 多查询检索+抓正文 → 分章节写作 → 汇总）
    research_max_queries: int = 8  # 规划阶段最多产出的子查询数
    research_search_top_k: int = 8  # 每个子查询联网搜索取多少条结果
    research_search_concurrency: int = 2  # 联网搜索并发上限（防搜索 API 429 限流）
    research_search_retries: int = 3  # 单个搜索失败/限流的重试次数
    research_fetch_top_n: int = 8  # 跨查询去重后最多抓取多少个网页正文
    research_fetch_concurrency: int = 4  # 抓正文并发上限
    research_fetch_timeout: int = 12  # 单个网页抓取超时（秒）
    research_source_truncate_chars: int = 3000  # 单个来源正文截断长度
    research_max_sections: int = 6  # 报告最多章节数
    research_kb_top_k: int = 6  # 知识库检索每查询取多少条
    research_mcp_enabled: bool = True  # 是否启用 MCP 增强检索（强模型+已配 MCP 才生效）
    research_mcp_max_iterations: int = 3  # MCP 增强工具循环最大轮数
    research_mcp_timeout: int = 40  # MCP 增强整步超时（秒）
    research_section_context_sources: int = 6  # 每章节写作喂入的相关来源上限
    # Deep Research v2：边检索边提炼 + 大纲优先 + 反思补搜
    research_distill_concurrency: int = 4  # 逐源提炼并发上限
    research_relevance_min: float = 0.3  # 提炼要点相关度低于此值丢弃
    research_max_learnings: int = 60  # 全局要点上限（控 token）
    research_reflection_rounds: int = 1  # 反思补搜轮数（0=关闭）
    research_reflection_max_queries: int = 4  # 每轮反思补充查询上限
    research_learnings_per_section: int = 10  # 每章节写作喂入的要点上限
    research_subquestions_per_section: int = 3  # 规划时每章节子问题数

    # 来源质量过滤（联网源按权威性+充实度打分排序，丢弃低质源，提升报告可靠性）
    research_source_quality_filter: bool = True  # 是否启用来源质量打分排序
    research_min_source_chars: int = 120  # 联网源正文少于此值视为抓取失败/登录墙，丢弃

    # 定时任务执行（单次研究的整体硬超时，防卡死任务长期占住 worker；跨平台用 asyncio.wait_for）
    research_task_timeout: int = 900  # 单次定时研究整体超时（秒）
    # 定时任务完成后推送通知用的站点地址（拼报告链接）
    notify_site_url: str = "https://cometxrzs.top"

    # ── V0.0.5 ② Verifier Loop（Loop Engineering 落地）──
    # 是否启用 Verifier Loop。关闭时 research engine 跳过质量复核环节,行为与之前完全一致。
    loop_enabled: bool = True
    # Verifier 选型:
    #   same  — 同 chat 模型新开 session + critic prompt(基线,无需额外配置)
    #   cross — 跨 family verifier 模型(需用户在模型配置里加 type=verifier 一条);未配则自动降级到 same
    loop_verifier_kind: str = "same"
    # 最大迭代轮数(N 轮不通过即 ForceExceed 标 unverified 仍展示)
    loop_max_iterations: int = 2

    # ── V0.0.5 ③ Agent Tracing(全链路可观测)──
    # 总开关:关闭后所有 tracer.span() 转空操作,零开销
    tracing_enabled: bool = True
    # 采样率(0~1):默认全采;高流量场景可降采样(本项目流量小,默认 1.0)
    tracing_sample_rate: float = 1.0
    # span 落库批量大小(累积到这么多条触发一次批量 insert,降低 DB 压力)
    tracing_batch_size: int = 20
    # span 落库 flush 间隔(秒):即使未到 batch_size,也强制定期刷新避免数据滞留
    tracing_flush_interval: float = 2.0
    # 内存队列上限(达到上限丢弃最旧 span 并 warning,保护进程内存)
    tracing_queue_maxsize: int = 5000

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
