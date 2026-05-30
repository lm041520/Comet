"""访问日志中间件：记录每个请求的方法、路径、状态码、耗时。"""
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.logging import get_logger

logger = get_logger("access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """记录访问日志。"""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        try:
            response = await call_next(request)
            cost_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "%s %s -> %d (%.1fms)",
                request.method,
                request.url.path,
                response.status_code,
                cost_ms,
            )
            return response
        except Exception:
            cost_ms = (time.perf_counter() - start) * 1000
            logger.warning(
                "%s %s -> 异常 (%.1fms)",
                request.method,
                request.url.path,
                cost_ms,
            )
            raise
