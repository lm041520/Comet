"""Span/Trace 异步批量落库 —— 不阻塞主流程。

设计:
- 一个 asyncio.Queue 收 SpanRecord/TraceRecord(及 trace 的更新事件)
- 一个后台 task 批量消费,凑够 `tracing_batch_size` 或 `tracing_flush_interval` 秒就 flush 一次
- 写库失败只 warning 不抛(永不影响业务)
- 队列上限保护:达到 `tracing_queue_maxsize` 丢最旧并 warning(优先内存安全 > 完整 trace)
- 进程退出时 `stop()` 排空残留数据后再关

落库映射:SpanRecord/TraceRecord(Pydantic) → AgentSpan/AgentTrace(ORM)。
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import update

from app.config import settings
from app.core.agent.tracing.models import SpanRecord, TraceRecord
from app.db.postgres import get_session
from app.models.agent_trace_model import AgentSpan, AgentTrace

logger = logging.getLogger(__name__)


@dataclass
class _SpanEvent:
    """span 落库事件:create(完整记录)或 update(只改字段)。"""
    kind: Literal["span_create", "trace_create", "trace_update"]
    span: SpanRecord | None = None
    trace: TraceRecord | None = None


class SpanRecorder:
    """异步批量落库器。模块级单例,通过 `get_recorder()` 获取。

    生命周期:
    - 应用启动调 `start()` 起后台 task
    - 业务通过 `push_span(record)` / `push_trace_create(record)` / `push_trace_update(record)` 入队
    - 应用关闭调 `stop()` 排空并退出
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[_SpanEvent] = asyncio.Queue(
            maxsize=settings.tracing_queue_maxsize
        )
        self._task: asyncio.Task | None = None
        self._stopping = False

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """启动后台消费 task(应用 lifespan 调用)。重复 start 幂等。"""
        if self.is_running():
            return
        self._stopping = False
        self._task = asyncio.create_task(self._consume_loop(), name="span_recorder")
        logger.info(
            "SpanRecorder 启动: batch=%d flush_interval=%.1fs queue_max=%d",
            settings.tracing_batch_size,
            settings.tracing_flush_interval,
            settings.tracing_queue_maxsize,
        )

    async def stop(self) -> None:
        """停止后台 task,先排空残留再退。"""
        if not self.is_running():
            return
        self._stopping = True
        # 等队列空 + task 结束
        try:
            await asyncio.wait_for(self._queue.join(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("SpanRecorder 关闭超时(5s),仍有 %d 条 span 未落库", self._queue.qsize())
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        logger.info("SpanRecorder 已停止")

    # ── 公共 push API(被 tracer.py 调用,非阻塞)──

    def push_trace_create(self, trace: TraceRecord) -> None:
        self._enqueue(_SpanEvent(kind="trace_create", trace=trace))

    def push_trace_update(self, trace: TraceRecord) -> None:
        """trace 结束时调,更新 finished_at / duration / 聚合 token+cost。"""
        self._enqueue(_SpanEvent(kind="trace_update", trace=trace))

    def push_span(self, span: SpanRecord) -> None:
        """span 结束时调。"""
        self._enqueue(_SpanEvent(kind="span_create", span=span))

    def _enqueue(self, ev: _SpanEvent) -> None:
        """入队,满则丢最旧并 warning(内存安全优先)。"""
        try:
            self._queue.put_nowait(ev)
        except asyncio.QueueFull:
            # 丢一条最旧的,再放新的
            try:
                _ = self._queue.get_nowait()
                self._queue.task_done()
                logger.warning(
                    "SpanRecorder 队列已满(max=%d),丢弃最旧 span 以容纳新数据",
                    settings.tracing_queue_maxsize,
                )
                self._queue.put_nowait(ev)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                logger.warning("SpanRecorder 入队失败,事件被丢弃: %s", ev.kind)

    # ── 内部:消费循环 ──

    async def _consume_loop(self) -> None:
        """批量消费:凑够 batch_size 或超 flush_interval 即 flush。"""
        buf: deque[_SpanEvent] = deque()
        try:
            while True:
                # 等第一条;若 stopping 且空,退出
                if not buf and not self._stopping:
                    ev = await self._queue.get()
                    buf.append(ev)
                # 短时间收满一批
                deadline = asyncio.get_event_loop().time() + settings.tracing_flush_interval
                while len(buf) < settings.tracing_batch_size:
                    remaining = deadline - asyncio.get_event_loop().time()
                    if remaining <= 0:
                        break
                    try:
                        ev = await asyncio.wait_for(self._queue.get(), timeout=remaining)
                        buf.append(ev)
                    except asyncio.TimeoutError:
                        break
                # 落库(失败只 warning,业务无感)
                if buf:
                    batch = list(buf)
                    buf.clear()
                    try:
                        await self._flush(batch)
                    except Exception as e:
                        logger.warning(
                            "SpanRecorder flush 失败,本批 %d 条丢弃: %s",
                            len(batch),
                            e,
                        )
                    finally:
                        # 无论成败都 task_done,让 queue.join() 能解
                        for _ in batch:
                            self._queue.task_done()
                # 停止信号 + 队列空 → 退出
                if self._stopping and self._queue.empty():
                    break
        except asyncio.CancelledError:
            logger.info("SpanRecorder 消费循环被取消")
            raise

    async def _flush(self, events: list[_SpanEvent]) -> None:
        """把一批事件落库。"""
        async for session in get_session():
            for ev in events:
                if ev.kind == "trace_create" and ev.trace:
                    session.add(_trace_to_orm(ev.trace))
                elif ev.kind == "span_create" and ev.span:
                    session.add(_span_to_orm(ev.span))
                elif ev.kind == "trace_update" and ev.trace:
                    await _update_trace(session, ev.trace)
            await session.commit()
            break


# ── ORM 映射 ──

def _trace_to_orm(t: TraceRecord) -> AgentTrace:
    return AgentTrace(
        id=t.trace_id,
        trace_id=t.trace_id,
        user_id=t.user_id,
        task_type=t.task_type,
        task_id=t.task_id,
        task_name=t.task_name,
        root_span_id=t.root_span_id,
        status=t.status,
        error_message=t.error_message,
        started_at=t.started_at,
        finished_at=t.finished_at,
        duration_ms=t.duration_ms,
        total_input_tokens=t.total_input_tokens,
        total_output_tokens=t.total_output_tokens,
        total_cached_tokens=t.total_cached_tokens,
        total_cost_cny=t.total_cost_cny,
        models_used=t.models_used,
        loop_run_id=t.loop_run_id,
        attributes=t.attributes,
    )


def _span_to_orm(s: SpanRecord) -> AgentSpan:
    return AgentSpan(
        id=s.span_id,
        span_id=s.span_id,
        parent_span_id=s.parent_span_id,
        trace_id=s.trace_id,
        span_type=s.span_type,
        name=s.name,
        status=s.status,
        error_message=s.error_message,
        started_at=s.started_at,
        finished_at=s.finished_at,
        duration_ms=s.duration_ms,
        model_name=s.model_name,
        input_tokens=s.input_tokens,
        output_tokens=s.output_tokens,
        cached_tokens=s.cached_tokens,
        cost_cny=s.cost_cny,
        payload=s.payload,
        attributes=s.attributes,
        iteration_id=s.iteration_id,
    )


async def _update_trace(session, t: TraceRecord) -> None:
    """trace 结束的更新事件:回填 finished_at/duration_ms/聚合数据。"""
    stmt = (
        update(AgentTrace)
        .where(AgentTrace.trace_id == t.trace_id)
        .values(
            status=t.status,
            error_message=t.error_message,
            finished_at=t.finished_at,
            duration_ms=t.duration_ms,
            total_input_tokens=t.total_input_tokens,
            total_output_tokens=t.total_output_tokens,
            total_cached_tokens=t.total_cached_tokens,
            total_cost_cny=t.total_cost_cny,
            models_used=t.models_used,
            loop_run_id=t.loop_run_id,
            root_span_id=t.root_span_id,
        )
    )
    await session.execute(stmt)


# ── 模块级单例 ──

_recorder: SpanRecorder | None = None


def get_recorder() -> SpanRecorder:
    """全局 SpanRecorder 单例(lazy 创建)。"""
    global _recorder
    if _recorder is None:
        _recorder = SpanRecorder()
    return _recorder
