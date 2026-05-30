"""模型配置路由：列表 / 新增 / 修改 / 删除 / 测试连接 / 设默认。"""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.response import success
from app.db.postgres import get_session
from app.models.user_model import User
from app.schemas.model_config_schema import ModelConfigCreate, ModelConfigUpdate
from app.services.model_config_service import ModelConfigService

router = APIRouter(prefix="/models", tags=["model_config"])


@router.get("")
async def list_models(
    type: str | None = Query(default=None, description="按类型过滤 chat/multimodal/embedding"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = ModelConfigService(session)
    configs = await service.list_configs(user.id, type)
    return success([service.to_out_dict(c) for c in configs])


@router.post("")
async def create_model(
    body: ModelConfigCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = ModelConfigService(session)
    config = await service.create(user.id, body)
    return success(service.to_out_dict(config), "创建成功")


@router.put("/{config_id}")
async def update_model(
    config_id: uuid.UUID,
    body: ModelConfigUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = ModelConfigService(session)
    config = await service.update(user.id, config_id, body)
    return success(service.to_out_dict(config), "更新成功")


@router.delete("/{config_id}")
async def delete_model(
    config_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await ModelConfigService(session).delete(user.id, config_id)
    return success(message="删除成功")


@router.post("/{config_id}/test")
async def test_model(
    config_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    ok, msg = await ModelConfigService(session).test(user.id, config_id)
    return success({"success": ok, "message": msg})


@router.put("/{config_id}/default")
async def set_default_model(
    config_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = ModelConfigService(session)
    config = await service.set_default(user.id, config_id)
    return success(service.to_out_dict(config), "已设为默认")
