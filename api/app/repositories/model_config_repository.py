"""模型配置数据访问层。所有查询强制带 user_id 隔离。"""
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model_config_model import ModelConfig


class ModelConfigRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_user(
        self, user_id: uuid.UUID, type_: str | None = None
    ) -> list[ModelConfig]:
        stmt = select(ModelConfig).where(ModelConfig.user_id == user_id)
        if type_:
            stmt = stmt.where(ModelConfig.type == type_)
        stmt = stmt.order_by(ModelConfig.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get(
        self, user_id: uuid.UUID, config_id: uuid.UUID
    ) -> ModelConfig | None:
        stmt = select(ModelConfig).where(
            ModelConfig.id == config_id, ModelConfig.user_id == user_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, config: ModelConfig) -> ModelConfig:
        self.session.add(config)
        await self.session.commit()
        await self.session.refresh(config)
        return config

    async def save(self, config: ModelConfig) -> ModelConfig:
        await self.session.commit()
        await self.session.refresh(config)
        return config

    async def delete(self, config: ModelConfig) -> None:
        await self.session.delete(config)
        await self.session.commit()

    async def clear_default(self, user_id: uuid.UUID, type_: str) -> None:
        """把某用户某类型的所有配置 is_default 置 False（设新默认前调用）。"""
        await self.session.execute(
            update(ModelConfig)
            .where(
                ModelConfig.user_id == user_id,
                ModelConfig.type == type_,
                ModelConfig.is_default.is_(True),
            )
            .values(is_default=False)
        )
