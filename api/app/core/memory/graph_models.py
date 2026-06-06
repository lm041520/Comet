"""记忆图谱的节点与边模型（Neo4j 写入用的内存数据结构）。

采用四层溯源结构，完整保留「记忆从哪段对话、哪个片段、哪句话来」：

    Dialogue（来源：一次对话 / 一段主动记住的文本）
      └─(:HAS_CHUNK)→ Chunk（按轮次 / token 切分的片段）
            └─(:HAS_STATEMENT)→ Statement（原子陈述句，带类型与时间属性）
                  └─(:MENTIONS)→ Entity（萃取出的实体）

在此之上构建语义层：

    Entity ─(:RELATION{predicate,...})→ Entity   实体间三元组关系
    Event  ─(:INVOLVES{role})→ Entity             事件涉及的实体（带 event_time，供时间线）
    Entity ─(:IN_COMMUNITY)→ Community            社区聚类（阶段7 使用）

所有节点 / 边都带 user_id 做多租户隔离；按业务键 MERGE 幂等写入。
"""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# ── 节点标签 ──
LABEL_DIALOGUE = "Dialogue"
LABEL_CHUNK = "Chunk"
LABEL_STATEMENT = "Statement"
LABEL_ENTITY = "Entity"
LABEL_EVENT = "Event"
LABEL_COMMUNITY = "Community"

# ── 关系类型 ──
REL_HAS_CHUNK = "HAS_CHUNK"  # Dialogue → Chunk
REL_HAS_STATEMENT = "HAS_STATEMENT"  # Chunk → Statement
REL_MENTIONS = "MENTIONS"  # Statement → Entity
REL_RELATION = "RELATION"  # Entity → Entity（三元组）
REL_INVOLVES = "INVOLVES"  # Event → Entity
REL_IN_COMMUNITY = "IN_COMMUNITY"  # Entity → Community

# ── 记忆来源 ──
SOURCE_AUTO = "auto"  # 对话自动萃取
SOURCE_MANUAL = "manual"  # 主动记住

# ── 陈述类型 / 时间类型 ──
STMT_FACT = "FACT"
STMT_OPINION = "OPINION"
STMT_PREDICTION = "PREDICTION"
STMT_SUGGESTION = "SUGGESTION"

TEMPORAL_STATIC = "STATIC"
TEMPORAL_DYNAMIC = "DYNAMIC"
TEMPORAL_ATEMPORAL = "ATEMPORAL"

# ── 记忆层级 ──
LAYER_SHORT_TERM = "short_term"  # 短期记忆：新萃取，未巩固
LAYER_LONG_TERM = "long_term"  # 长期记忆：经巩固提升

# ── 连接强度 ──
CONNECT_STRONG = "strong"  # 参与三元组关系的实体
CONNECT_WEAK = "weak"  # 仅被陈述提及的实体


def _new_id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now()


class DialogueNode(BaseModel):
    """一次萃取的来源根节点：一段对话或一条主动记住的文本。"""

    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_new_id)
    user_id: str
    content: str  # 来源全文
    source: str = SOURCE_MANUAL  # auto | manual
    source_message_id: str | None = None  # 对话消息溯源（阶段5 接入）
    dialog_at: datetime = Field(default_factory=_now)  # 来源发生时间
    created_at: datetime = Field(default_factory=_now)


class ChunkNode(BaseModel):
    """对话片段：按轮次 / token 切分，承上启下用于溯源。"""

    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_new_id)
    user_id: str
    dialog_id: str
    content: str
    speaker: str | None = None  # user | assistant
    sequence: int = 0
    created_at: datetime = Field(default_factory=_now)


class StatementNode(BaseModel):
    """原子陈述句：萃取的最小语义单元，带类型与时间属性。"""

    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_new_id)
    user_id: str
    chunk_id: str
    statement: str
    stmt_type: str = STMT_FACT  # FACT | OPINION | PREDICTION | SUGGESTION
    temporal_type: str = TEMPORAL_STATIC  # STATIC | DYNAMIC | ATEMPORAL
    speaker: str | None = None
    valid_at: datetime | None = None
    invalid_at: datetime | None = None
    dialog_at: datetime | None = None
    embedding: list[float] | None = None
    # 记忆动力学
    importance: float = 0.5  # 重要度（LLM 评分）
    confidence: float = 0.8  # 置信度（LLM 评分）
    memory_layer: str = LAYER_SHORT_TERM  # 记忆层级（新萃取默认短期）
    access_count: int = 0  # 被检索命中次数（检索侧回写）
    last_access_at: datetime | None = None  # 最近被检索时间
    # 情绪（含情绪时填，与 PG 情绪表并存）
    has_emotional_state: bool = False
    emotion_type: str | None = None
    emotion_intensity: float | None = None
    emotion_keywords: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)


class EntityNode(BaseModel):
    """实体节点：萃取出的画像实体（人/组织/知识/偏好/目标等）。"""

    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_new_id)
    user_id: str
    name: str
    type: str  # 受控实体类型中文标签
    description: str = ""
    aliases: list[str] = Field(default_factory=list)
    name_embedding: list[float] | None = None
    community_id: str | None = None
    # 记忆动力学
    importance: float = 0.5  # 重要度（LLM 评分，合并时取较大值）
    confidence: float = 0.8  # 置信度（LLM 评分）
    memory_layer: str = LAYER_SHORT_TERM  # 记忆层级
    access_count: int = 0  # 被检索命中次数
    last_access_at: datetime | None = None  # 最近被检索时间
    mention_count: int = 1  # 被陈述提及累计次数（合并时累加）
    connect_strength: str = CONNECT_STRONG  # strong | weak | both
    # 画像增强（巩固任务 LLM 回写）
    core_facts: list[str] = Field(default_factory=list)  # 核心事实
    traits: list[str] = Field(default_factory=list)  # 特质标签
    last_consolidated_at: datetime | None = None  # 最近巩固时间
    created_at: datetime = Field(default_factory=_now)


class EventNode(BaseModel):
    """事件节点：带 event_time，供记忆时间线展示。"""

    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_new_id)
    user_id: str
    title: str
    description: str = ""
    event_time: datetime | None = None
    embedding: list[float] | None = None
    created_at: datetime = Field(default_factory=_now)


class CommunityNode(BaseModel):
    """社区节点：实体聚类结果（阶段7 使用）。"""

    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_new_id)
    user_id: str
    name: str
    summary: str = ""
    member_count: int = 0
    created_at: datetime = Field(default_factory=_now)


class RelationEdge(BaseModel):
    """实体间三元组关系：Entity -[:RELATION]-> Entity。"""

    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_new_id)
    user_id: str
    source_id: str  # 主语实体 id
    target_id: str  # 宾语实体 id
    predicate: str  # 受控谓词中文标签
    predicate_surface: str = ""  # 原文中的关系表达
    source_text: str = ""  # 关系来源陈述句原文
    statement_id: str | None = None  # 溯源 Statement
    value: str | None = None  # 附加值（如数量、内容）
    valid_at: datetime | None = None
    invalid_at: datetime | None = None
    importance: float = 0.5  # 关系重要度（LLM 评分）
    confidence: float = 0.8  # 关系置信度（LLM 评分）
    access_count: int = 0  # 被检索命中次数
    created_at: datetime = Field(default_factory=_now)


class MentionEdge(BaseModel):
    """陈述提及实体：Statement -[:MENTIONS]-> Entity。"""

    model_config = ConfigDict(extra="ignore")
    user_id: str
    statement_id: str
    entity_id: str
    connect_strength: str = "strong"  # strong | weak
    created_at: datetime = Field(default_factory=_now)


class InvolvesEdge(BaseModel):
    """事件涉及实体：Event -[:INVOLVES]-> Entity。"""

    model_config = ConfigDict(extra="ignore")
    user_id: str
    event_id: str
    entity_id: str
    role: str = ""
    created_at: datetime = Field(default_factory=_now)


__all__ = [
    "LABEL_DIALOGUE",
    "LABEL_CHUNK",
    "LABEL_STATEMENT",
    "LABEL_ENTITY",
    "LABEL_EVENT",
    "LABEL_COMMUNITY",
    "REL_HAS_CHUNK",
    "REL_HAS_STATEMENT",
    "REL_MENTIONS",
    "REL_RELATION",
    "REL_INVOLVES",
    "REL_IN_COMMUNITY",
    "SOURCE_AUTO",
    "SOURCE_MANUAL",
    "STMT_FACT",
    "STMT_OPINION",
    "STMT_PREDICTION",
    "STMT_SUGGESTION",
    "TEMPORAL_STATIC",
    "TEMPORAL_DYNAMIC",
    "TEMPORAL_ATEMPORAL",
    "LAYER_SHORT_TERM",
    "LAYER_LONG_TERM",
    "CONNECT_STRONG",
    "CONNECT_WEAK",
    "DialogueNode",
    "ChunkNode",
    "StatementNode",
    "EntityNode",
    "EventNode",
    "CommunityNode",
    "RelationEdge",
    "MentionEdge",
    "InvolvesEdge",
]
