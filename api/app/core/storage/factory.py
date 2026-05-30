"""存储后端工厂：按 settings.storage_backend 返回单例实例。"""
from functools import lru_cache

from app.config import settings
from app.core.storage.base import StorageBackend


@lru_cache
def get_storage() -> StorageBackend:
    backend = settings.storage_backend.lower()
    if backend == "oss":
        from app.core.storage.oss_storage import OssStorage

        return OssStorage()
    if backend == "local":
        from app.core.storage.local_storage import LocalStorage

        return LocalStorage()
    raise ValueError(f"不支持的存储后端: {settings.storage_backend}")


def build_file_key(user_id: str, category: str, file_id: str, ext: str) -> str:
    """生成文件 key：{user_id}/{category}/{file_id}.ext。

    category 形如 documents / images。
    """
    ext = ext if ext.startswith(".") else f".{ext}"
    return f"{user_id}/{category}/{file_id}{ext}"
