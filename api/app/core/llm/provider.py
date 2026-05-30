"""Provider 元信息与连接测试。

所有 provider 走 OpenAI 兼容协议：
- chat/multimodal：POST {base_url}/chat/completions
- embedding：POST {base_url}/embeddings
连接测试发一个最小请求，验证 key/base_url/model 是否可用。
"""
import httpx

# 各 provider 的默认 base_url（用户可覆盖）
PROVIDER_DEFAULT_BASE_URL: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "doubao": "https://ark.cn-beijing.volces.com/api/v3",
    "deepseek": "https://api.deepseek.com/v1",
}


async def test_connection(
    type_: str, base_url: str, api_key: str, model_name: str
) -> tuple[bool, str]:
    """实际调一次目标 API 验证可用性。返回 (是否成功, 中文提示)。"""
    base = base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            if type_ == "embedding":
                resp = await client.post(
                    f"{base}/embeddings",
                    headers=headers,
                    json={"model": model_name, "input": "ping"},
                )
            else:
                # chat / multimodal 都用 chat/completions 最小请求
                resp = await client.post(
                    f"{base}/chat/completions",
                    headers=headers,
                    json={
                        "model": model_name,
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1,
                    },
                )
    except httpx.TimeoutException:
        return False, "连接超时，请检查 base_url 是否可达"
    except httpx.RequestError as e:
        return False, f"连接失败：{e}"

    if resp.status_code == 200:
        return True, "连接成功"
    if resp.status_code in (401, 403):
        return False, "API Key 无效或无权限"
    if resp.status_code == 404:
        return False, "模型不存在或 base_url 路径错误"
    # 其它错误，尽量带上服务端返回的信息
    detail = ""
    try:
        body = resp.json()
        detail = body.get("error", {}).get("message", "") or str(body)
    except Exception:
        detail = resp.text[:200]
    return False, f"测试失败（HTTP {resp.status_code}）：{detail}"
