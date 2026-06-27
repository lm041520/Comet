"""全局 Tracer —— 非侵入式埋点 API。

业务侧使用:
    tracer = get_tracer()

    # 起一次完整任务 trace(研究/对话/定时任务):
    async with tracer.trace(user_id, task_type="research", task_name=...) as trace_ctx:
        async with tracer.span("planner", span_type="planner") as sp:
            sp.set_attribute("plan_size", 5)
            ...
        async with tracer.span("retriever", span_type="retriever") as sp:
            ...
        # LLM 调用:在 LLMClient 内部自带 llm_call span
        async with tracer.llm_span("写正文", model_name="deepseek-v4-pro") as sp:
            ...
            sp.set_tokens(input=1200, output=800)

设计要点:
1. ContextVar 维护当前 trace 和 span 栈,自动 parent_id 关联
2. 嵌套 span 支持(`with` 内 `with`),退出按栈顺序关闭
3. 关闭时同步把记录推入 SpanRecorder 异步队列
4. tracing_enabled=False 时所有 API 转空操作(NoOpTrace/NoOpSpan)
5. 采样:trace 开始时按 sample_rate 决定;采样掉的 trace 走 NoOp 路径,零开销
"""
from __future__ import annotations

import contextvars
import logging
import random
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from app.config import settings
from app.core.agent.tracing.models import SpanRecord, TraceRecord
from app.core.agent.tracing.pricing import estimate_cost_cny
from app.core.agent.tracing.span_recorder import get_recorder

logger = logging.getLogger(__name__)


# ContextVar:当前 trace 与当前 span 栈(asyncio 任务安全)
_current_trace: contextvars.ContextVar[TraceRecord | None] = contextvars.ContextVar(
    "tracing.current_trace", default=None
)
_current_span: contextvars.ContextVar[SpanRecord | None] = contextvars.ContextVar(
    "tracing.current_span", default=None
)


class _SpanHandle:
    """span 句柄,业务代码持有它读写属性/tokens/状态。"""

    __slots__ = ("_record", "_noop")

    def __init__(self, record: SpanRecord | None = None) -> None:
        self._record = record
        self._noop = record is None

    @property
    def span_id(self) -> uuid.UUID | None:
        return self._record.span_id if self._record else None

    @property
    def is_noop(self) -> bool:
        return self._noop

    def set_attribute(self, key: str, value: Any) -> None:
        if self._noop:
            return
        # 仅接受 JSON 可序列化的简单值;复杂对象转 str
        try:
            self._record.attributes[key] = value  # type: ignore[union-attr]
        except Exception:
            self._record.attributes[key] = str(value)  # type: ignore[union-attr]

    def set_attributes(self, mapping: dict[str, Any]) -> None:
        if self._noop:
            return
        for k, v in mapping.items():
            self.set_attribute(k, v)

    def set_payload(self, key: str, value: Any) -> None:
        """payload 存输入输出的摘要(不存全文)。"""
        if self._noop:
            return
        self._record.payload[key] = value  # type: ignore[union-attr]

    def set_tokens(
        self,
        input: int = 0,
        output: int = 0,
        cached: int = 0,
        model_name: str | None = None,
    ) -> None:
        """LLM/embedding span 记录用量;自动算 cost 并累加到 trace。"""
        if self._noop or self._record is None:
            return
        self._record.input_tokens = input
        self._record.output_tokens = output
        self._record.cached_tokens = cached
        if model_name:
            self._record.model_name = model_name
        self._record.cost_cny = estimate_cost_cny(
            self._record.model_name, input, output, cached
        )
        # 累加到当前 trace(若有)
        tr = _current_trace.get()
        if tr is not None:
            tr.total_input_tokens += input
            tr.total_output_tokens += output
            tr.total_cached_tokens += cached
            tr.total_cost_cny = round(tr.total_cost_cny + self._record.cost_cny, 6)
            if model_name and model_name not in tr.models_used:
                tr.models_used.append(model_name)

    def set_iteration_id(self, iteration_id: uuid.UUID | None) -> None:
        """verifier/repair span 关联到 ② loop_iterations 的某一轮。"""
        if self._noop or self._record is None:
            return
        self._record.iteration_id = iteration_id

    def mark_error(self, message: str) -> None:
        if self._noop or self._record is None:
            return
        self._record.status = "error"
        self._record.error_message = message[:1000]  # 防超长


class Tracer:
    """全局 Tracer。线程/任务安全(基于 ContextVar)。"""

    @asynccontextmanager
    async def trace(
        self,
        user_id: uuid.UUID,
        task_type: str,
        task_id: uuid.UUID | None = None,
        task_name: str | None = None,
        loop_run_id: uuid.UUID | None = None,
        attributes: dict[str, Any] | None = None,
    ):
        """启动一次完整 Agent 任务的 trace。

        采样:按 `tracing_sample_rate` 决定是否真采;不采时走 NoOp 路径完全零开销。
        """
        if not settings.tracing_enabled or random.random() > settings.tracing_sample_rate:
            yield _NoopTraceCtx()
            return

        record = TraceRecord(
            user_id=user_id,
            task_type=task_type,
            task_id=task_id,
            task_name=task_name,
            loop_run_id=loop_run_id,
            started_at=datetime.now(),
            attributes=attributes or {},
        )
        trace_token = _current_trace.set(record)
        # trace 创建事件先入队(create 记录)
        try:
            get_recorder().push_trace_create(record)
        except Exception as e:
            logger.warning("trace 创建入队失败: %s", e)

        try:
            yield _TraceCtx(record)
            record.status = "ok"
        except Exception as e:
            record.status = "error"
            record.error_message = str(e)[:1000]
            raise
        finally:
            record.finished_at = datetime.now()
            record.duration_ms = int(
                (record.finished_at - record.started_at).total_seconds() * 1000
            )
            try:
                get_recorder().push_trace_update(record)
            except Exception as e:
                logger.warning("trace 更新入队失败: %s", e)
            _current_trace.reset(trace_token)

    @asynccontextmanager
    async def span(
        self,
        name: str,
        span_type: str = "other",
        attributes: dict[str, Any] | None = None,
    ):
        """启动一个 span(可嵌套)。"""
        tr = _current_trace.get()
        if not settings.tracing_enabled or tr is None:
            # 无 active trace 或 tracing 关闭 → NoOp
            yield _SpanHandle(None)
            return

        parent = _current_span.get()
        record = SpanRecord(
            trace_id=tr.trace_id,
            parent_span_id=parent.span_id if parent else None,
            span_type=span_type,
            name=name,
            started_at=datetime.now(),
            attributes=attributes or {},
        )
        # 根 span 回填 trace.root_span_id
        if parent is None and tr.root_span_id is None:
            tr.root_span_id = record.span_id
        span_token = _current_span.set(record)
        handle = _SpanHandle(record)

        try:
            yield handle
            if record.status == "running":
                record.status = "ok"
        except Exception as e:
            record.status = "error"
            record.error_message = str(e)[:1000]
            raise
        finally:
            record.finished_at = datetime.now()
            record.duration_ms = int(
                (record.finished_at - record.started_at).total_seconds() * 1000
            )
            try:
                get_recorder().push_span(record)
            except Exception as e:
                logger.warning("span 入队失败: %s", e)
            _current_span.reset(span_token)

    @asynccontextmanager
    async def llm_span(
        self,
        name: str,
        model_name: str | None = None,
        attributes: dict[str, Any] | None = None,
    ):
        """LLM 调用 span 的便捷封装(预填 model_name + span_type=llm_call)。"""
        attrs = dict(attributes or {})
        async with self.span(name, span_type="llm_call", attributes=attrs) as sp:
            if model_name and not sp.is_noop and sp._record is not None:
                sp._record.model_name = model_name
            yield sp


class _TraceCtx:
    """trace 上下文句柄,业务侧可用它读 trace_id / 设置 loop_run_id。"""

    __slots__ = ("_record",)

    def __init__(self, record: TraceRecord) -> None:
        self._record = record

    @property
    def trace_id(self) -> uuid.UUID:
        return self._record.trace_id

    def set_loop_run_id(self, loop_run_id: uuid.UUID | None) -> None:
        """trace 进行中得到 loop_run_id 时回填(如 research engine 创建 LoopRun 后)。"""
        self._record.loop_run_id = loop_run_id

    def set_attribute(self, key: str, value: Any) -> None:
        self._record.attributes[key] = value


class _NoopTraceCtx:
    """采样掉或 tracing 关闭时返回的空对象。"""

    trace_id = uuid.UUID(int=0)

    def set_loop_run_id(self, loop_run_id: uuid.UUID | None) -> None:
        pass

    def set_attribute(self, key: str, value: Any) -> None:
        pass


# 全局单例
_tracer = Tracer()


def get_tracer() -> Tracer:
    """获取全局 Tracer。"""
    return _tracer


def current_trace_id() -> uuid.UUID | None:
    """快速读当前 trace_id(无 trace 返回 None)。供业务在 SSE 事件里带上 trace_id。"""
    tr = _current_trace.get()
    return tr.trace_id if tr else None


def current_span_iteration_id() -> uuid.UUID | None:
    """当前 span 的 loop iteration_id(verifier 调用前设置过)。"""
    sp = _current_span.get()
    return sp.iteration_id if sp else None
