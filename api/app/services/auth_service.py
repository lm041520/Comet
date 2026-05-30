"""鉴权业务服务：注册、登录、刷新、改密。"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user_model import User
from app.repositories.user_repository import UserRepository

logger = get_logger(__name__)


class AuthService:
    def __init__(self, session: AsyncSession):
        self.repo = UserRepository(session)

    async def register(self, username: str, password: str) -> User:
        if await self.repo.get_by_username(username):
            logger.warning("注册失败，用户名已存在: %s", username)
            raise BizError("用户名已存在", code=1001, status_code=409)
        user = await self.repo.create(username, hash_password(password))
        logger.info("用户注册成功: username=%s id=%s", username, user.id)
        return user

    async def authenticate(self, username: str, password: str) -> User:
        user = await self.repo.get_by_username(username)
        if not user or not verify_password(password, user.password_hash):
            logger.warning("登录失败，用户名或密码错误: %s", username)
            raise BizError("用户名或密码错误", code=1002, status_code=401)
        logger.info("用户登录成功: username=%s id=%s", username, user.id)
        return user

    def issue_tokens(self, user: User) -> tuple[str, str]:
        sub = str(user.id)
        return create_access_token(sub), create_refresh_token(sub)

    async def refresh(self, refresh_token: str) -> tuple[str, str]:
        payload = decode_token(refresh_token)
        if not payload or payload.get("type") != "refresh":
            raise BizError("刷新令牌无效", code=1003, status_code=401)
        user = await self.repo.get_by_id(uuid.UUID(payload["sub"]))
        if not user:
            raise BizError("用户不存在", code=1004, status_code=401)
        return self.issue_tokens(user)

    async def change_password(
        self, user: User, old_password: str, new_password: str
    ) -> None:
        if not verify_password(old_password, user.password_hash):
            logger.warning("改密失败，原密码错误: id=%s", user.id)
            raise BizError("原密码错误", code=1005, status_code=400)
        await self.repo.update_password(user, hash_password(new_password))
        logger.info("用户修改密码成功: id=%s", user.id)
