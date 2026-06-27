"""Tracing 模块的 Pydantic 数据结构 —— 与 ORM 模型解耦。

记录 Span/Trace 在内存中的活态结构,落库前由 span_recorder 拍扁为 dict 入库。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SpanRecord(BaseModel):
    """一个 Span 的运行时数据。close() 后由 recorder 异步落库。"""

    span_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    parent_span_id: uuid.UUID | None = None
    trace_id: uuid.UUID
    span_type: str  # planner / retriever / writer / tool_call / verifier / repair / mcp_call / llm_call / other
    name: str

    status: str = "running"  # running / ok / error
    error_message: str | None = None

    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None

    # LLM 调用 span 才用
    model_name: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost_cny: float = 0.0

    payload: dict[str, Any] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)

    # 关联 ② Verifier Loop 某一轮迭代(verifier/repair span 时填)
    iteration_id: uuid.UUID | None = None


class TraceRecord(BaseModel):
    """一次完整 Agent 任务的运行时数据。Tracer.start_trace() 创建,end_trace() 落库。"""

    trace_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    user_id: uuid.UUID
    task_type: str
    task_id: uuid.UUID | None = None
    task_name: str | None = None
    root_span_id: uuid.UUID | None = None

    status: str = "running"
    error_message: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None

    # 聚合(span 落库时由 recorder 累加)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cached_tokens: int = 0
    total_cost_cny: float = 0.0
    models_used: list[str] = Field(default_factory=list)

    loop_run_id: uuid.UUID | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
