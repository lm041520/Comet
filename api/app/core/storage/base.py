"""存储后端抽象接口。"""
from abc import ABC, abstractmethod


class StorageBackend(ABC):
    """文件存储后端统一接口。

    file_key 为对象在存储中的逻辑路径，约定按用户隔离：
    {user_id}/documents/{file_id}.ext 或 {user_id}/images/{file_id}.ext
    """

    @abstractmethod
    async def save(self, file_key: str, content: bytes) -> str:
        """保存文件，返回 file_key。"""
        raise NotImplementedError

    @abstractmethod
    async def get(self, file_key: str) -> bytes:
        """读取文件内容。"""
        raise NotImplementedError

    @abstractmethod
    async def delete(self, file_key: str) -> None:
        """删除文件。"""
        raise NotImplementedError

    @abstractmethod
    async def exists(self, file_key: str) -> bool:
        """文件是否存在。"""
        raise NotImplementedError

    @abstractmethod
    def get_url(self, file_key: str, expires: int = 3600) -> str:
        """获取可访问 URL（OSS 为签名 URL；本地为后端文件接口路径）。"""
        raise NotImplementedError
