"""评测独立配置：直接用 .env.eval 里的模型 key 建 LLMClient，不依赖 app 的「用户+模型配置表」。

设计：评测自带模型凭证 + 固定评测命名空间 EVAL_USER_ID（数据写它名下、可整体清理），
从而完全自包含、可复现，不需要在系统里先建用户/配模型/灌数据。
"""
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv

from app.core.llm.client import LLMClient

# 加载评测专用环境变量（与 app 的 .env 隔离）
load_dotenv(Path(__file__).parent / ".env.eval")

# 固定评测命名空间：所有评测数据写在此 user_id 下，便于隔离与一键清理
EVAL_USER_ID = uuid.UUID("eee00000-0000-0000-0000-0000000000ee")


def _build(prefix: str) -> LLMClient | None:
    base = os.getenv(f"{prefix}_BASE_URL")
    key = os.getenv(f"{prefix}_KEY")
    model = os.getenv(f"{prefix}_MODEL")
    if not (base and key and model):
        return None
    return LLMClient(base_url=base, api_key=key, model_name=model)


def embed_client() -> LLMClient:
    c = _build("EVAL_EMBED")
    if c is None:
        raise RuntimeError("缺少 EVAL_EMBED_* 配置（请复制 .env.eval.example 为 .env.eval 并填写）")
    return c


def chat_client() -> LLMClient:
    c = _build("EVAL_CHAT")
    if c is None:
        raise RuntimeError("缺少 EVAL_CHAT_* 配置（请复制 .env.eval.example 为 .env.eval 并填写）")
    return c


def rerank_client() -> LLMClient | None:
    """可选；未配置返回 None（评测时跳过 rerank 相关项）。"""
    return _build("EVAL_RERANK")
