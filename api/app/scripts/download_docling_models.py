"""预下载 Docling 模型（部署时运行一次，模型不进 git）。

用法：
    uv run python -m app.scripts.download_docling_models
    uv run python -m app.scripts.download_docling_models --force   # 强制重新下载

默认下载到 settings.rag_docling_cache_dir（./storage/docling-models）。
"""
import argparse
import sys

from app.config import settings
from app.core.rag.ingestion.parsers.docling_models import download_docling_models


def main() -> int:
    parser = argparse.ArgumentParser(description="下载 Docling 解析所需模型")
    parser.add_argument("--force", action="store_true", help="强制重新下载（忽略已完成标记）")
    parser.add_argument(
        "--dir",
        default=settings.rag_docling_cache_dir,
        help="模型下载目录（默认取配置 rag_docling_cache_dir）",
    )
    args = parser.parse_args()
    try:
        target = download_docling_models(args.dir, force=args.force)
    except Exception as exc:  # noqa: BLE001 — 顶层命令，打印错误并返回非零
        print(f"下载失败：{exc}", file=sys.stderr)
        return 1
    print(f"Docling 模型已就绪：{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
