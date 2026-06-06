"""Neo4j 记忆图谱 schema：唯一约束 + 向量索引 + 全文索引。

应用启动时调用 ensure_graph_schema() 幂等创建。中文全文检索用 cjk 分词器，
向量索引维度与 embedding 配置一致（默认 1024，余弦相似度）。
"""
from app.config import settings
from app.core.logging import get_logger
from app.core.memory.graph_models import (
    LABEL_CHUNK,
    LABEL_COMMUNITY,
    LABEL_DIALOGUE,
    LABEL_ENTITY,
    LABEL_EVENT,
    LABEL_STATEMENT,
)
from app.db.neo4j import get_driver

logger = get_logger(__name__)

VECTOR_DIMS = settings.embedding_dims

# 唯一约束：核心节点按 id 唯一，保证 MERGE 幂等、并发安全
_CONSTRAINTS = [
    f"CREATE CONSTRAINT dialogue_id_unique IF NOT EXISTS "
    f"FOR (n:{LABEL_DIALOGUE}) REQUIRE n.id IS UNIQUE",
    f"CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS "
    f"FOR (n:{LABEL_CHUNK}) REQUIRE n.id IS UNIQUE",
    f"CREATE CONSTRAINT statement_id_unique IF NOT EXISTS "
    f"FOR (n:{LABEL_STATEMENT}) REQUIRE n.id IS UNIQUE",
    f"CREATE CONSTRAINT entity_id_unique IF NOT EXISTS "
    f"FOR (n:{LABEL_ENTITY}) REQUIRE n.id IS UNIQUE",
    f"CREATE CONSTRAINT event_id_unique IF NOT EXISTS "
    f"FOR (n:{LABEL_EVENT}) REQUIRE n.id IS UNIQUE",
    f"CREATE CONSTRAINT community_id_unique IF NOT EXISTS "
    f"FOR (n:{LABEL_COMMUNITY}) REQUIRE n.id IS UNIQUE",
]

# 普通属性索引：按 user_id 过滤是高频操作
_PROPERTY_INDEXES = [
    f"CREATE INDEX entity_user_idx IF NOT EXISTS FOR (n:{LABEL_ENTITY}) ON (n.user_id)",
    f"CREATE INDEX event_user_idx IF NOT EXISTS FOR (n:{LABEL_EVENT}) ON (n.user_id)",
    f"CREATE INDEX statement_user_idx IF NOT EXISTS FOR (n:{LABEL_STATEMENT}) ON (n.user_id)",
    f"CREATE INDEX entity_name_idx IF NOT EXISTS FOR (n:{LABEL_ENTITY}) ON (n.name)",
    # 记忆分层 / 重要度：巩固任务与检索排序的过滤维度
    f"CREATE INDEX entity_layer_idx IF NOT EXISTS FOR (n:{LABEL_ENTITY}) ON (n.memory_layer)",
    f"CREATE INDEX statement_layer_idx IF NOT EXISTS FOR (n:{LABEL_STATEMENT}) ON (n.memory_layer)",
]

# 全文索引（cjk 分词，支持中文关键词检索）
_FULLTEXT_INDEXES = [
    f"CREATE FULLTEXT INDEX entity_fulltext IF NOT EXISTS "
    f"FOR (n:{LABEL_ENTITY}) ON EACH [n.name, n.description, n.aliases] "
    f"OPTIONS {{ indexConfig: {{ `fulltext.analyzer`: 'cjk' }} }}",
    f"CREATE FULLTEXT INDEX statement_fulltext IF NOT EXISTS "
    f"FOR (n:{LABEL_STATEMENT}) ON EACH [n.statement] "
    f"OPTIONS {{ indexConfig: {{ `fulltext.analyzer`: 'cjk' }} }}",
    f"CREATE FULLTEXT INDEX event_fulltext IF NOT EXISTS "
    f"FOR (n:{LABEL_EVENT}) ON EACH [n.title, n.description] "
    f"OPTIONS {{ indexConfig: {{ `fulltext.analyzer`: 'cjk' }} }}",
]

# 向量索引（余弦相似度，维度与 embedding 一致）
_VECTOR_INDEXES = [
    (
        f"CREATE VECTOR INDEX entity_embedding_index IF NOT EXISTS "
        f"FOR (n:{LABEL_ENTITY}) ON n.name_embedding "
        f"OPTIONS {{ indexConfig: {{ `vector.dimensions`: {VECTOR_DIMS}, "
        f"`vector.similarity_function`: 'cosine' }} }}"
    ),
    (
        f"CREATE VECTOR INDEX statement_embedding_index IF NOT EXISTS "
        f"FOR (n:{LABEL_STATEMENT}) ON n.embedding "
        f"OPTIONS {{ indexConfig: {{ `vector.dimensions`: {VECTOR_DIMS}, "
        f"`vector.similarity_function`: 'cosine' }} }}"
    ),
    (
        f"CREATE VECTOR INDEX event_embedding_index IF NOT EXISTS "
        f"FOR (n:{LABEL_EVENT}) ON n.embedding "
        f"OPTIONS {{ indexConfig: {{ `vector.dimensions`: {VECTOR_DIMS}, "
        f"`vector.similarity_function`: 'cosine' }} }}"
    ),
]


async def ensure_graph_schema() -> None:
    """幂等创建记忆图谱的约束与索引。应用启动时调用。"""
    driver = get_driver()
    statements = _CONSTRAINTS + _PROPERTY_INDEXES + _FULLTEXT_INDEXES + _VECTOR_INDEXES
    async with driver.session() as session:
        for cypher in statements:
            try:
                await session.run(cypher)
            except Exception as e:
                # 单条失败不阻断其余（如旧版 Neo4j 不支持向量索引）
                logger.warning("创建图 schema 语句失败（跳过）: %s | %s", cypher[:60], e)
    logger.info("记忆图谱 schema 初始化完成")


__all__ = ["ensure_graph_schema", "VECTOR_DIMS"]
