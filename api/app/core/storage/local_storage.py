"""本地目录存储后端（开发用）。"""
import asyncio
from pathlib import Path

from app.config import settings
from app.core.logging import get_logger
from app.core.storage.base import StorageBackend

logger = get_logger(__name__)


class LocalStorage(StorageBackend):
    def __init__(self) -> None:
        self.root = Path(settings.storage_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, file_key: str) -> Path:
        return self.root / file_key

    async def save(self, file_key: str, content: bytes) -> str:
        def _write() -> None:
            p = self._path(file_key)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)

        await asyncio.to_thread(_write)
        logger.info("本地存储保存文件: %s (%d bytes)", file_key, len(content))
        return file_key

    async def get(self, file_key: str) -> bytes:
        return await asyncio.to_thread(self._path(file_key).read_bytes)

    async def delete(self, file_key: str) -> None:
        def _del() -> None:
            p = self._path(file_key)
            if p.exists():
                p.unlink()

        await asyncio.to_thread(_del)
        logger.info("本地存储删除文件: %s", file_key)

    async def exists(self, file_key: str) -> bool:
        return await asyncio.to_thread(self._path(file_key).exists)

    def get_url(self, file_key: str, expires: int = 3600) -> str:
        # 本地存储通过后端文件接口访问
        return f"/api/files/{file_key}"
