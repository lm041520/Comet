"""Agent 全链路可观测 ORM 模型 —— PostgreSQL agent_traces / agent_spans 两张表。

V0.0.5 ③ Tracing 落地的数据底座:
- `agent_traces`:一次完整的 Agent 任务执行(一份研究报告 / 一次对话 / 一次定时任务)
- `agent_spans`:Trace 内每个执行节点(planner / retriever / writer / tool_call / verifier / repair / llm_call …)

字段命名兼容 OpenTelemetry GenAI semantic convention(`gen_ai.system / gen_ai.usage.*`),
未来要导出到 OTel Collector / Jaeger / Tempo,只需改输出格式,无需改库表结构。
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


# task_type 枚举(字符串便于扩展;一次完整任务的语义类别)
TASK_TYPE_RESEARCH = "research"
TASK_TYPE_CHAT = "chat"
TASK_TYPE_AGENT_TASK = "agent_task"
TASK_TYPE_VERIFY = "verify"
TASK_TYPE_REPAIR = "repair"

# span_type 枚举(执行节点的语义类别;埋点时按这个分类便于聚合)
SPAN_TYPE_PLANNER = "planner"
SPAN_TYPE_RETRIEVER = "retriever"
SPAN_TYPE_WRITER = "writer"
SPAN_TYPE_TOOL_CALL = "tool_call"
SPAN_TYPE_VERIFIER = "verifier"
SPAN_TYPE_REPAIR = "repair"
SPAN_TYPE_MCP_CALL = "mcp_call"
SPAN_TYPE_LLM_CALL = "llm_call"
SPAN_TYPE_OTHER = "other"

# status 枚举
STATUS_RUNNING = "running"
STATUS_OK = "ok"
STATUS_ERROR = "error"


class AgentTrace(Base):
    """一次完整的 Agent 任务执行 = 一条 Trace。

    所有 Span 通过 `trace_id` 挂到这条 Trace 下面;
    成本/token 在 Span 落库时累加到这里(异步,不强一致,允许短暂滞后)。
    """

    __tablename__ = "agent_traces"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # 全局 trace_id(展示用,与 id 同源 UUID,便于跨日志/前端定位)
    trace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, index=True
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    # 任务类型 + 关联的业务 id(不加 FK 解耦:业务删除时 trace 仍保留作 audit)
    task_type: Mapped[str] = mapped_column(String(32), index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    # 人话名(如「深度研究:量子计算最新进展」),便于列表页展示
    task_name: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # 根 span(便于前端时间线从根开始展开)
    root_span_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    # 状态机:running / ok / error
    status: Mapped[str] = mapped_column(String(16), default=STATUS_RUNNING, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 时间(duration 在 finish 时回填,便于前端列表排序/聚合)
    started_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 成本与 token 聚合(span 落库时累加;cached_tokens 单独算便于查缓存命中率)
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_cny: Mapped[float] = mapped_column(Float, default=0.0)

    # 模型审计:这次任务用到了哪些模型(JSON 列表,便于跨模型成本对比)
    models_used: Mapped[list] = mapped_column(JSONB, default=list)

    # 关联 ② Verifier Loop(若该 trace 走了 verify),便于「报告页 → 评分卡 → 查看执行轨迹」下钻
    loop_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    # 扩展属性(放暂未结构化的元数据,如 user_agent / client_ip / debug flag 等)
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict)

    __table_args__ = (
        Index("ix_agent_traces_user_started", "user_id", "started_at"),
    )


class AgentSpan(Base):
    """Trace 内的一个执行节点(planner/retriever/writer/tool_call/verifier/repair/llm_call …)。"""

    __tablename__ = "agent_spans"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # 业务上 span 唯一 id(便于 parent_span_id 引用,与 id 同源 UUID)
    span_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, index=True
    )
    # 父 span(根 span 该字段为 NULL)
    parent_span_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    # 所属 trace(冗余存便于按 trace 一次查全部 span)
    trace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_traces.trace_id", ondelete="CASCADE"),
        index=True,
    )

    # span_type 与 name:类型用于聚合归因,name 用于前端展示
    span_type: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(128))

    # 状态机:running / ok / error
    status: Mapped[str] = mapped_column(String(16), default=STATUS_RUNNING, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 时间
    started_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # LLM 调用相关(llm_call span 时填充;其他 span 默认 0/None)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_cny: Mapped[float] = mapped_column(Float, default=0.0)

    # payload:输入/输出摘要(不存全文,存哈希 + 长度 + 关键参数,避免表膨胀)
    # 大文本需要详情时,业务表(research_reports.content_md / messages.content 等)里查
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    # attributes:OTel GenAI 标准属性 + 业务扩展属性
    # 如 {gen_ai.system: "deepseek", gen_ai.request.model: "deepseek-v3", ...}
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict)

    # 关联 ② Verifier Loop 的某一轮迭代(verifier/repair span 时填充),
    # 实现「报告页评分卡 → 时间线 → 第 N 轮 verify/repair span」精确定位
    iteration_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    __table_args__ = (
        Index("ix_agent_spans_trace_started", "trace_id", "started_at"),
        Index("ix_agent_spans_type_status", "span_type", "status"),
    )
