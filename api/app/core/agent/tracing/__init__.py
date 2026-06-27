"""Agent 全链路可观测(Tracing)模块。

V0.0.5 ③ 落地的核心抽象:
- `tracer`:全局 Tracer 单例,提供 `async with tracer.span(...)` 上下文管理器埋点
- `span_recorder`:异步批量写库,不阻塞主流程
- `pricing`:内置模型单价表,llm_call span 按 model + tokens 算 cost_cny
- `otel_attrs`:OpenTelemetry GenAI semantic convention 常量,字段名兼容标准
- `models`:Trace/Span 的 Pydantic 数据结构,与 ORM 解耦

设计原则:
1. 非侵入:业务代码只需 `async with tracer.span("name", span_type=...) as span:` 包裹
2. 不阻塞:span 数据进内存队列,后台 task 批量落 PG;写库失败也不影响业务
3. 关闭即零开销:`settings.tracing_enabled=False` 时所有 API 转空操作
4. 兼容 OTel:attributes 用 `gen_ai.*` 标准名,未来导出 OTel Collector 零成本
"""
from app.core.agent.tracing.models import (
    SpanRecord,
    TraceRecord,
)
from app.core.agent.tracing.tracer import Tracer, get_tracer

__all__ = [
    "SpanRecord",
    "TraceRecord",
    "Tracer",
    "get_tracer",
]
