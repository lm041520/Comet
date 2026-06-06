"""LLM 调用客户端：基于用户的模型配置调用 OpenAI 兼容接口。

封装 embedding / chat / 多模态 / rerank 调用，供解析、检索、问答复用。
对网络抖动 / 服务端 5xx / 连接中断做有限重试（指数退避），提升萃取稳定性。
"""
import asyncio

import httpx

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# 连接级重试：网络抖动/连接中断/服务端 5xx/429 时重试
_MAX_RETRIES = 3
_RETRY_BACKOFF = 1.5  # 秒，第 n 次重试等待 _RETRY_BACKOFF * n
_RETRY_STATUS = {429, 500, 502, 503, 504}


async def _post_with_retry(
    url: str, *, headers: dict, json: dict, timeout: float
) -> dict:
    """带重试的 POST，返回解析后的 JSON。

    重试场景：httpx 传输异常（连接中断/读超时/对端关闭）与可重试的 HTTP 状态（429/5xx）。
    其余 4xx（如鉴权/参数错误）不重试，直接抛出。
    """
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, headers=headers, json=json)
            if resp.status_code in _RETRY_STATUS:
                raise httpx.HTTPStatusError(
                    f"可重试状态 {resp.status_code}", request=resp.request, response=resp
                )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            # 仅可重试状态进入重试；其余 4xx 直接抛
            if e.response is not None and e.response.status_code not in _RETRY_STATUS:
                raise
            last_exc = e
        except (httpx.TransportError, httpx.HTTPError) as e:
            # 连接中断 / 读超时 / incomplete chunked read 等传输异常
            last_exc = e
        if attempt < _MAX_RETRIES - 1:
            wait = _RETRY_BACKOFF * (attempt + 1)
            logger.warning(
                "LLM 请求失败，第 %d/%d 次重试（等待 %.1fs）: %r",
                attempt + 1, _MAX_RETRIES, wait, last_exc,
            )
            await asyncio.sleep(wait)
    raise last_exc if last_exc else RuntimeError("LLM 请求失败")


class LLMClient:
    """一个 provider 配置对应一个 client（base_url + api_key + model）。"""

    def __init__(self, base_url: str, api_key: str, model_name: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def embed(
        self, texts: list[str], dimensions: int | None = None
    ) -> list[list[float]]:
        """文本批量向量化。返回与输入等长的向量列表。

        dimensions 控制输出维度（默认取 settings.embedding_dims），
        与 ES 索引维度保持一致；支持指定维度的 provider（如智谱 embedding-3）会按此裁剪。
        """
        dims = dimensions or settings.embedding_dims
        payload: dict = {
            "model": self.model_name,
            "input": texts,
            "dimensions": dims,
        }
        data = await _post_with_retry(
            f"{self.base_url}/embeddings",
            headers=self._headers, json=payload, timeout=60,
        )
        # OpenAI 兼容：data.data[i].embedding，按 index 排序
        items = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in items]

    async def embed_one(self, text: str, dimensions: int | None = None) -> list[float]:
        vecs = await self.embed([text], dimensions=dimensions)
        return vecs[0]

    async def chat(
        self, messages: list[dict], temperature: float = 0.3, max_tokens: int = 2048
    ) -> str:
        """非流式对话，返回完整文本。"""
        data = await _post_with_retry(
            f"{self.base_url}/chat/completions",
            headers=self._headers,
            json={
                "model": self.model_name,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=120,
        )
        return data["choices"][0]["message"]["content"]

    async def vision(
        self, prompt: str, image_b64: str, mime: str = "image/jpeg", max_tokens: int = 1024
    ) -> str:
        """多模态看图：传入提示词 + base64 图片，返回模型描述文本。"""
        data_url = f"data:{mime};base64,{image_b64}"
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ]
        data = await _post_with_retry(
            f"{self.base_url}/chat/completions",
            headers=self._headers,
            json={
                "model": self.model_name,
                "messages": messages,
                "max_tokens": max_tokens,
            },
            timeout=120,
        )
        return data["choices"][0]["message"]["content"]

    async def rerank(
        self, query: str, documents: list[str], top_n: int | None = None
    ) -> list[tuple[int, float]]:
        """重排，返回 [(原始索引, 相关性分数), ...]，按分数降序。"""
        payload = {"model": self.model_name, "query": query, "documents": documents}
        if top_n:
            payload["top_n"] = top_n
        data = await _post_with_retry(
            f"{self.base_url}/rerank", headers=self._headers, json=payload, timeout=60,
        )
        results = data.get("results", [])
        return [
            (r["index"], r.get("relevance_score", 0.0))
            for r in sorted(
                results, key=lambda x: x.get("relevance_score", 0.0), reverse=True
            )
        ]
