"""FastAPI 应用入口。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.controllers.router import api_router
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.core.request_context import RequestContextMiddleware
from app.db import elastic, neo4j, postgres, redis

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("%s 启动完成", settings.app_name)
    yield
    # 关闭：释放长连接 / 连接池
    await postgres.close()
    await elastic.close()
    await neo4j.close()
    await redis.close()
    logger.info("%s 已关闭，连接池释放完成", settings.app_name)


def create_app() -> FastAPI:
    app = FastAPI(
        title=f"{settings.app_name} API",
        description="彗记 Comet — 个人 AI 知识库与记忆助手",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # 请求上下文（request_id）中间件
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
