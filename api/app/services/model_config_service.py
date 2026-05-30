"""模型配置业务服务：CRUD、连接测试、设默认。"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError
from app.core.llm.provider import test_connection
from app.core.logging import get_logger
from app.core.security import decrypt_secret, encrypt_secret, mask_secret
from app.models.model_config_model import ModelConfig
from app.repositories.model_config_repository import ModelConfigRepository
from app.schemas.model_config_schema import ModelConfigCreate, ModelConfigUpdate

logger = get_logger(__name__)


class ModelConfigService:
    def __init__(self, session: AsyncSession):
        self.repo = ModelConfigRepository(session)

    async def list_configs(
        self, user_id: uuid.UUID, type_: str | None = None
    ) -> list[ModelConfig]:
        return await self.repo.list_by_user(user_id, type_)

    async def _get_or_404(
        self, user_id: uuid.UUID, config_id: uuid.UUID
    ) -> ModelConfig:
        config = await self.repo.get(user_id, config_id)
        if not config:
            raise BizError("模型配置不存在", code=2001, status_code=404)
        return config

    async def create(
        self, user_id: uuid.UUID, body: ModelConfigCreate
    ) -> ModelConfig:
        config = ModelConfig(
            user_id=user_id,
            type=body.type,
            provider=body.provider,
            name=body.name,
            model_name=body.model_name,
            api_key_encrypted=encrypt_secret(body.api_key),
            base_url=body.base_url,
            capability=body.capability,
            is_default=body.is_default,
        )
        # 设为默认则先清掉同类型旧默认
        if body.is_default:
            await self.repo.clear_default(user_id, body.type)
        created = await self.repo.create(config)
        logger.info(
            "创建模型配置: user=%s type=%s provider=%s id=%s",
            user_id,
            body.type,
            body.provider,
            created.id,
        )
        return created

    async def update(
        self, user_id: uuid.UUID, config_id: uuid.UUID, body: ModelConfigUpdate
    ) -> ModelConfig:
        config = await self._get_or_404(user_id, config_id)
        if body.name is not None:
            config.name = body.name
        if body.model_name is not None:
            config.model_name = body.model_name
        if body.base_url is not None:
            config.base_url = body.base_url
        if body.capability is not None:
            config.capability = body.capability
        if body.api_key:  # 非空才更新 key
            config.api_key_encrypted = encrypt_secret(body.api_key)
        return await self.repo.save(config)

    async def delete(self, user_id: uuid.UUID, config_id: uuid.UUID) -> None:
        config = await self._get_or_404(user_id, config_id)
        await self.repo.delete(config)
        logger.info("删除模型配置: user=%s id=%s", user_id, config_id)

    async def set_default(
        self, user_id: uuid.UUID, config_id: uuid.UUID
    ) -> ModelConfig:
        config = await self._get_or_404(user_id, config_id)
        await self.repo.clear_default(user_id, config.type)
        config.is_default = True
        return await self.repo.save(config)

    async def test(
        self, user_id: uuid.UUID, config_id: uuid.UUID
    ) -> tuple[bool, str]:
        config = await self._get_or_404(user_id, config_id)
        api_key = decrypt_secret(config.api_key_encrypted)
        ok, msg = await test_connection(
            config.type, config.base_url, api_key, config.model_name
        )
        logger.info(
            "模型连接测试: user=%s id=%s success=%s msg=%s",
            user_id,
            config_id,
            ok,
            msg,
        )
        return ok, msg

    @staticmethod
    def to_out_dict(config: ModelConfig) -> dict:
        """转出参 dict，api_key 以掩码呈现。"""
        return {
            "id": str(config.id),
            "type": config.type,
            "provider": config.provider,
            "name": config.name,
            "model_name": config.model_name,
            "api_key_masked": mask_secret(decrypt_secret(config.api_key_encrypted)),
            "base_url": config.base_url,
            "capability": config.capability,
            "is_default": config.is_default,
            "created_at": config.created_at.isoformat(),
        }
