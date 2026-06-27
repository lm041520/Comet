"""模型 token 单价表 + 成本核算。

设计:
- 内置主流 provider 单价(2026 年公开价格,CNY/千 tokens),覆盖常用 OpenAI 兼容供应商
- 未命中走默认兜底单价(中等档位,避免 cost=0 误导)
- 不读 DB(本版),未来要个性化单价时,可加 `user_model_pricing` 表覆盖
- cached_tokens 走优惠价(很多 provider 缓存 50~80 折),不命中时与 input 同价

单价单位:**CNY per 1K tokens**(便于 OpenAI/智谱等 v1 接口直接乘)。
"""
from __future__ import annotations

# (input_per_1k_cny, output_per_1k_cny, cached_per_1k_cny)
# cached 默认 = input * 0.4(平均水位,准确值因 provider 而异)
_PRICE_TABLE: dict[str, tuple[float, float, float]] = {
    # OpenAI 主流(按 2026.06 公开价 + 7 汇率)
    "gpt-4o": (0.0175, 0.0700, 0.0088),
    "gpt-4o-mini": (0.00105, 0.0042, 0.00053),
    "gpt-4-turbo": (0.070, 0.210, 0.035),
    "gpt-3.5-turbo": (0.0035, 0.0105, 0.0018),
    # DeepSeek
    "deepseek-v4-pro": (0.002, 0.008, 0.0005),
    "deepseek-v3": (0.002, 0.008, 0.0005),
    "deepseek-chat": (0.002, 0.008, 0.0005),
    "deepseek-reasoner": (0.004, 0.016, 0.001),
    # 智谱 GLM
    "glm-4.6": (0.003, 0.012, 0.0015),
    "glm-4-plus": (0.05, 0.05, 0.025),
    "glm-4-air": (0.001, 0.001, 0.0005),
    "glm-4-flash": (0.0001, 0.0001, 0.00005),
    "glm-4v-plus": (0.01, 0.01, 0.005),
    "glm-4v": (0.05, 0.05, 0.025),
    # 通义千问
    "qwen-max": (0.024, 0.096, 0.012),
    "qwen-plus": (0.0008, 0.002, 0.0004),
    "qwen-turbo": (0.0003, 0.0006, 0.00015),
    "qwen-vl-max": (0.02, 0.02, 0.01),
    "qwen-vl-plus": (0.008, 0.008, 0.004),
    # 豆包
    "doubao-pro-32k": (0.0008, 0.002, 0.0004),
    "doubao-lite-32k": (0.0003, 0.0006, 0.00015),
    # Embedding(只算 input,output 单价填 0)
    "embedding-3": (0.0005, 0.0, 0.0),
    "text-embedding-3-small": (0.00014, 0.0, 0.0),
    "text-embedding-3-large": (0.00091, 0.0, 0.0),
    "text-embedding-v3": (0.0005, 0.0, 0.0),
    "text-embedding-v2": (0.0005, 0.0, 0.0),
    # Rerank(按 input 算,output 0)
    "bge-reranker-v2-m3": (0.0001, 0.0, 0.0),
    "gte-rerank": (0.0001, 0.0, 0.0),
}

# 未命中时的兜底单价:按中等档位估,宁可高估也不让 cost=0 误导
_FALLBACK = (0.005, 0.015, 0.0025)


def estimate_cost_cny(
    model_name: str | None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cached_tokens: int = 0,
) -> float:
    """按 model + tokens 估算 CNY 成本。

    cached_tokens 走单独优惠价,且会从 input_tokens 中扣除避免重复计费。
    模型名做小写归一与简单后缀剥离(如 `deepseek-chat-v3` 命中 `deepseek-chat`)。
    """
    if not model_name:
        in_p, out_p, cached_p = _FALLBACK
    else:
        in_p, out_p, cached_p = _resolve_price(model_name)

    # cached 不与 input 重复计费
    fresh_input = max(0, input_tokens - cached_tokens)
    cost = (
        fresh_input * in_p / 1000.0
        + output_tokens * out_p / 1000.0
        + cached_tokens * cached_p / 1000.0
    )
    return round(cost, 6)


def _resolve_price(model: str) -> tuple[float, float, float]:
    """模型名归一查表;先精确匹配,再前缀匹配(如 `glm-4.6-preview` → `glm-4.6`)。"""
    key = model.strip().lower()
    if key in _PRICE_TABLE:
        return _PRICE_TABLE[key]
    # 前缀匹配:取最长前缀命中
    best: tuple[float, float, float] | None = None
    best_len = 0
    for k, v in _PRICE_TABLE.items():
        if key.startswith(k) and len(k) > best_len:
            best = v
            best_len = len(k)
    if best is not None:
        return best
    return _FALLBACK


def list_known_models() -> list[str]:
    """返回所有已知模型名(供 admin 面板展示/对齐)。"""
    return sorted(_PRICE_TABLE.keys())
