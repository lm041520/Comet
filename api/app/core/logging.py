"""全局日志系统。

特性：
- 控制台 + 文件轮转双输出，统一格式
- 压制 httpx / neo4j 等第三方噪音日志
- 敏感信息过滤（API Key / token / 密码不进日志）
- get_logger(__name__) 工厂获取 logger
"""
import logging
import logging.handlers
import re
from pathlib import Path

from app.config import settings

_LOG_FORMAT = "%(asctime)s | %(levelname)-5s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 敏感字段：日志里出现这些键的值会被打码
_SENSITIVE_PATTERNS = [
    re.compile(r"(api[_-]?key\"?\s*[:=]\s*\"?)([^\"\s,}]+)", re.IGNORECASE),
    re.compile(r"(token\"?\s*[:=]\s*\"?)([^\"\s,}]+)", re.IGNORECASE),
    re.compile(r"(password\"?\s*[:=]\s*\"?)([^\"\s,}]+)", re.IGNORECASE),
    re.compile(r"(secret\"?\s*[:=]\s*\"?)([^\"\s,}]+)", re.IGNORECASE),
    re.compile(r"(sk-[A-Za-z0-9]{8})[A-Za-z0-9]+", re.IGNORECASE),
]


class SensitiveFilter(logging.Filter):
    """把日志消息中的敏感值替换成掩码。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            msg = record.msg
            for pat in _SENSITIVE_PATTERNS[:-1]:
                msg = pat.sub(r"\1***", msg)
            msg = _SENSITIVE_PATTERNS[-1].sub(r"\1***", msg)
            record.msg = msg
        return True


_initialized = False


def setup_logging() -> None:
    """初始化全局日志，应用启动时调用一次（幂等）。"""
    global _initialized
    if _initialized:
        return

    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())
    root.handlers.clear()

    formatter = logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT)
    sensitive = SensitiveFilter()

    if settings.log_to_console:
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        ch.addFilter(sensitive)
        root.addHandler(ch)

    if settings.log_to_file:
        log_path = Path(settings.log_file_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            filename=str(log_path),
            maxBytes=settings.log_max_bytes,
            backupCount=settings.log_backup_count,
            encoding="utf-8",
        )
        fh.setFormatter(formatter)
        fh.addFilter(sensitive)
        root.addHandler(fh)

    # 压制第三方噪音
    for noisy in ["httpx", "httpcore", "neo4j", "neo4j.notifications", "elastic_transport"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _initialized = True
    logging.getLogger(__name__).info("日志系统初始化完成")


def get_logger(name: str | None = None) -> logging.Logger:
    """获取 logger，name 一般传 __name__。"""
    return logging.getLogger(name)
