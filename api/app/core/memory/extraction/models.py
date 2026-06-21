"""萃取流水线的中间数据模型（LLM 结构化输出 + 流水线传递）。

仅在萃取过程内部使用，最终转换成 graph_models 的节点/边写入 Neo4j。
"""
from pydantic import BaseModel, ConfigDict, Field, field_validator


def _to_float(v: object, default: float | None) -> float | None:
    """把 LLM 可能返回的空串 / 非法值 / None 容错转成 float，失败回退默认值。

    模型常把评分字段填成 ""、"高"、漏填等，直接喂给 float 校验会整条萃取失败。
    """
    if isinstance(v, bool):  # bool 是 int 子类，单独挡掉
        return default
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return default
        try:
            return float(s)
        except ValueError:
            return default
    return default


# ── 陈述抽取 ──

class ExtractedStatement(BaseModel):
    """从文本切出的原子陈述句。"""

    model_config = ConfigDict(extra="ignore")
    statement: str
    statement_type: str = "FACT"  # FACT | OPINION | PREDICTION | SUGGESTION
    temporal_type: str = "STATIC"  # STATIC | DYNAMIC | ATEMPORAL
    has_unsolved_reference: bool = False
    # 记忆动力学：LLM 评分（0~1），缺省给中性默认
    importance: float = 0.5  # 重要度
    confidence: float = 0.8  # 置信度
    # 情绪（含情绪时填，与 PG 情绪表并存：图谱情绪用于带情绪的记忆检索/画像）
    has_emotional_state: bool = False
    emotion_type: str | None = None
    emotion_intensity: float | None = None
    emotion_keywords: list[str] = Field(default_factory=list)

    @field_validator("importance", mode="before")
    @classmethod
    def _v_importance(cls, v):
        return _to_float(v, 0.5)

    @field_validator("confidence", mode="before")
    @classmethod
    def _v_confidence(cls, v):
        return _to_float(v, 0.8)

    @field_validator("emotion_intensity", mode="before")
    @classmethod
    def _v_emotion_intensity(cls, v):
        return _to_float(v, None)


class StatementExtractionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    statements: list[ExtractedStatement] = Field(default_factory=list)


# ── 三元组抽取 ──

class ExtractedEvent(BaseModel):
    """LLM 抽出的事件（一次性发生、有时间的经历）。"""

    model_config = ConfigDict(extra="ignore")
    title: str  # 事件标题，如「完成项目上线」
    description: str = ""  # 事件描述
    event_time: str | None = None  # ISO 时间 或 NULL
    participants: list[str] = Field(default_factory=list)  # 涉及实体名（关联到已抽实体）


class ExtractedEntity(BaseModel):
    """LLM 抽出的实体（chunk 内局部 idx 用于关联 triplet）。"""

    model_config = ConfigDict(extra="ignore")
    entity_idx: int = -1  # LLM 偶尔漏填；-1 表示无法关联三元组（不影响实体本身入图）
    name: str
    type: str = "其他"  # LLM 偶尔漏填；缺省归入「其他」未知桶，避免整条结果校验失败
    description: str = ""
    importance: float = 0.5  # 重要度（LLM 评分 0~1）
    confidence: float = 0.8  # 置信度（LLM 评分 0~1）

    @field_validator("importance", mode="before")
    @classmethod
    def _v_importance(cls, v):
        return _to_float(v, 0.5)

    @field_validator("confidence", mode="before")
    @classmethod
    def _v_confidence(cls, v):
        return _to_float(v, 0.8)


class ExtractedTriplet(BaseModel):
    """LLM 抽出的三元组。"""

    model_config = ConfigDict(extra="ignore")
    subject_name: str
    subject_id: int = -1  # LLM 偶尔漏填；-1 在编排时 .get 不命中即跳过该三元组
    predicate: str = "关联于"  # 漏填则按弱关系处理（后续 normalize_predicate 兜底）
    predicate_surface: str = ""
    object_name: str
    object_id: int = -1
    value: str | None = None
    valid_at: str | None = None
    invalid_at: str | None = None
    importance: float = 0.5  # 关系重要度（LLM 评分 0~1）
    confidence: float = 0.8  # 关系置信度（LLM 评分 0~1）

    @field_validator("importance", mode="before")
    @classmethod
    def _v_importance(cls, v):
        return _to_float(v, 0.5)

    @field_validator("confidence", mode="before")
    @classmethod
    def _v_confidence(cls, v):
        return _to_float(v, 0.8)


class TripletExtractionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    entities: list[ExtractedEntity] = Field(default_factory=list)
    triplets: list[ExtractedTriplet] = Field(default_factory=list)
    events: list[ExtractedEvent] = Field(default_factory=list)

    # 单条不合法（缺关键名字字段）就丢弃该条，不让整段对话的萃取整体失败
    @field_validator("entities", "triplets", "events", mode="before")
    @classmethod
    def _drop_malformed(cls, v, info):
        if not isinstance(v, list):
            return []
        field = info.field_name
        out = []
        for it in v:
            if not isinstance(it, dict):
                continue
            if field == "entities":
                if not str(it.get("name") or "").strip():
                    continue  # 实体缺名字 → 丢弃
            elif field == "triplets":
                if not (str(it.get("subject_name") or "").strip()
                        and str(it.get("object_name") or "").strip()):
                    continue  # 三元组缺主/宾名 → 丢弃
            elif field == "events":
                if not str(it.get("title") or "").strip():
                    continue  # 事件缺标题 → 丢弃
            out.append(it)
        return out


# ── 实体去重判定 ──

class DedupDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")
    same_entity: bool = False
    canonical_idx: int = 0
    confidence: float = 0.0
    reason: str = ""

    @field_validator("confidence", mode="before")
    @classmethod
    def _v_confidence(cls, v):
        return _to_float(v, 0.0)


__all__ = [
    "ExtractedStatement",
    "StatementExtractionResult",
    "ExtractedEvent",
    "ExtractedEntity",
    "ExtractedTriplet",
    "TripletExtractionResult",
    "DedupDecision",
]
