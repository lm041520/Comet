"""Docling 模型的运行时下载与就绪检查。

模型权重体积较大（数百 MB），不进 git 仓库，改为：
- 部署时用 `python -m app.scripts.download_docling_models` 预下载；
- 或首次解析复杂 PDF 时懒加载自动下载（无网络则降级 PyMuPDF）。

用一个 marker 文件标记"已下载完成"，避免每次都重复检查/下载。
"""
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger(__name__)

_MARKER_NAME = ".download_complete"
# 进程内只尝试自动下载一次，失败后不反复重试（交由 PyMuPDF 降级）
_auto_download_attempted = False


def _marker_path(cache_dir: Path) -> Path:
    return cache_dir / _MARKER_NAME


def models_ready(cache_dir: Path) -> bool:
    """已完成下载（存在 marker）视为就绪。"""
    return _marker_path(cache_dir).exists()


def download_docling_models(cache_dir: str | Path, *, force: bool = False) -> Path:
    """下载 Docling 所需模型到 cache_dir，成功后写 marker。

    供部署脚本显式调用；抛出的异常由调用方处理。
    """
    target = Path(cache_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    if models_ready(target) and not force:
        logger.info("Docling 模型已就绪，跳过下载: %s", target)
        return target

    from docling.utils.model_downloader import download_models

    logger.info("开始下载 Docling 模型到 %s（首次较慢，请耐心等待）", target)
    download_models(output_dir=target, force=force, progress=True)
    _marker_path(target).write_text("ok", encoding="utf-8")
    logger.info("Docling 模型下载完成: %s", target)
    return target


def ensure_docling_models(cache_dir: str | Path) -> str | None:
    """确保模型就绪：缺失则本进程尝试自动下载一次。

    返回 None 表示就绪；返回错误字符串表示不可用（调用方据此降级）。
    """
    global _auto_download_attempted
    target = Path(cache_dir).resolve()
    if models_ready(target):
        return None
    if _auto_download_attempted:
        return "Docling 模型未就绪且本进程已尝试下载失败"
    _auto_download_attempted = True
    try:
        download_docling_models(target)
        return None
    except Exception as exc:  # noqa: BLE001 — 下载失败要降级而非中断
        logger.warning("Docling 模型自动下载失败，将降级 PyMuPDF: %s", exc)
        return str(exc)[:300]
