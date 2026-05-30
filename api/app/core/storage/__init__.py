"""文件存储抽象层。

通过 get_storage() 获取存储后端实例，业务层只依赖 StorageBackend 接口，
底层用本地目录还是阿里云 OSS 由 settings.storage_backend 决定，切换不改业务代码。
"""
from app.core.storage.base import StorageBackend
from app.core.storage.factory import build_file_key, get_storage

__all__ = ["StorageBackend", "get_storage", "build_file_key"]
