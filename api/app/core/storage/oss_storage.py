"""阿里云 OSS 存储后端（部署用）。

oss2 SDK 为同步实现，统一用 asyncio.to_thread 包成异步，避免阻塞事件循环。
"""
import asyncio

import oss2

from app.config import settings
from app.core.logging import get_logger
from app.core.storage.base import StorageBackend

logger = get_logger(__name__)


class OssStorage(StorageBackend):
    def __init__(self) -> None:
        if not all(
            [
                settings.oss_endpoint,
                settings.oss_access_key_id,
                settings.oss_access_key_secret,
                settings.oss_bucket_name,
            ]
        ):
            raise RuntimeError("OSS 配置不完整，请检查 .env 中 OSS_* 项")
        auth = oss2.Auth(settings.oss_access_key_id, settings.oss_access_key_secret)
        self.bucket = oss2.Bucket(
            auth, settings.oss_endpoint, settings.oss_bucket_name
        )

    async def save(self, file_key: str, content: bytes) -> str:
        await asyncio.to_thread(self.bucket.put_object, file_key, content)
        logger.info("OSS 保存文件: %s (%d bytes)", file_key, len(content))
        return file_key

    async def get(self, file_key: str) -> bytes:
        def _read() -> bytes:
            return self.bucket.get_object(file_key).read()

        return await asyncio.to_thread(_read)

    async def delete(self, file_key: str) -> None:
        await asyncio.to_thread(self.bucket.delete_object, file_key)
        logger.info("OSS 删除文件: %s", file_key)

    async def exists(self, file_key: str) -> bool:
        return await asyncio.to_thread(self.bucket.object_exists, file_key)

    def get_url(self, file_key: str, expires: int = 3600) -> str:
        # 生成带签名的临时访问 URL
        return self.bucket.sign_url("GET", file_key, expires)
