# ASR 语音输入 — 设计与八股（后端）

> V0.0.3 的输入体验特性：在对话/群聊里用语音说话，转成文字填进输入框。采用**双路设计**——路 A 浏览器免费的 Web Speech（纯前端，不在后端范围）+ 路 B 配置云端 ASR 模型走后端转写（DashScope Paraformer / OpenAI Whisper）。**后端只负责路 B 的云端转写**。本篇只讲后端。

---

## 一、功能定位与需求

- **双路语音输入**：
  - **路 A（浏览器免费）**：用浏览器原生 `SpeechRecognition`（Web Speech API），不花钱、不走后端，作为默认/降级方案。**纯前端实现，不在本篇后端范围**，这里只点明它的存在以说明整体设计。
  - **路 B（云端升级）**：用户在模型配置里加一个 `asr` 类型的模型（DashScope Paraformer 或 OpenAI Whisper），前端把录音上传到后端，后端调云端 ASR 转写。识别质量更好、跨浏览器一致。
- **后端职责**：只做路 B——接收音频 → 存储拿公网 URL → 取用户默认 ASR 配置 → 调云端转写 → 返回文本 → 用完即弃删音频。
- **未配 ASR 优雅降级**：用户没配 `asr` 模型时后端返回 `code=2010`，前端据此降级到路 A（Web Speech）或提示。
- **转写填框不自动发**：转写结果填进输入框待用户确认，不直接发送。

---

## 二、数据模型与迁移

### 2.1 复用 `model_configs` 表，新增 `asr` 类型（无迁移）

ASR **没有新建任何表**，而是复用既有的模型配置表 `model_configs`（`api/app/models/model_config_model.py`），把 ASR 当成一种新的模型 `type`。

关键点：**`type` 列本来就是 `String(32)`，不是数据库枚举**，所以新增一个 `"asr"` 取值**不需要任何迁移**——数据库层早就能存任意字符串。改动只发生在 Pydantic 校验层：

```python
# api/app/schemas/model_config_schema.py
ModelTypeT = Literal["chat", "multimodal", "embedding", "rerank", "websearch", "asr"]
```

在 `Literal` 里加上 `"asr"`，新类型就能通过入参校验、被前端配置页选择并存库。`provider` 沿用既有枚举：DashScope 走 `qwen`，Whisper 走 `openai`。

这是「把扩展点设计成开放字符串列 + 应用层枚举校验」带来的好处：增加模型类型零迁移，只动 schema 的 `Literal`。

---

## 三、核心实现与代码路径

分层：`chat_controller.py` 的 `POST /chat/transcribe`（接收音频、编排）→ `core/asr/transcriber.py`（按 provider 适配的转写实现）；配置侧 `core/llm/provider.py` 的 `_test_asr`（连接测试分支）。

### 3.1 转写实现（`api/app/core/asr/transcriber.py`）

统一入口 `transcribe(provider, api_key, model_name, audio_url)`，按 provider 分两条实现，失败抛 `BizError`（中文提示）由上层兜底：

```python
async def transcribe(provider, api_key, model_name, audio_url) -> str:
    if provider in ("qwen",):
        return await _transcribe_dashscope(api_key, model_name or "paraformer-v2", audio_url)
    if provider in ("openai",):
        return await _transcribe_whisper(api_key, model_name or "whisper-1", audio_url)
    raise BizError(f"暂不支持的 ASR 服务商：{provider}", code=2030)
```

**① DashScope Paraformer（异步录音文件识别）** —— `_transcribe_dashscope`：

这是阿里云的**异步**接口，三步走：

1. **提交任务**：POST `.../audio/asr/transcription`，请求头带 `X-DashScope-Async: enable`，body 里 `input.file_urls` 传**可公网访问的音频 URL**（所以音频必须先存储拿 URL，见 3.2），`parameters.language_hints` 给中英文提示。返回拿 `output.task_id`。
2. **轮询任务状态**：循环 GET `.../tasks/{task_id}`，每 `1.5s` 一次、最多 `40` 次（约 60s，匹配录音 ≤60s）。`task_status` 为 `SUCCEEDED` 取结果；`FAILED`/`CANCELED` 抛错；超时抛「识别超时」。
3. **拉转写结果 JSON 取文本**（`_extract_dashscope_text`）：成功的 `output.results` 里每项给的是一个 `transcription_url`，再 GET 这个 URL 拿到真正的转写 JSON，从 `transcripts[].text` 拼出文本。空结果抛「未识别到语音内容」。

**② OpenAI Whisper（同步）** —— `_transcribe_whisper`：

简单得多：下载音频字节 → multipart 上传 `POST /v1/audio/transcriptions` → 同步返回 `text`。

### 3.2 转写编排接口（`POST /chat/transcribe`，`chat_controller.py`）

```python
@router.post("/chat/transcribe")
async def transcribe_audio(file: UploadFile, user, session):
    # 1) 取用户默认 ASR 配置；没配则报 2010（前端据此降级）
    config = await get_default_config_for_type(session, user.id, "asr", "语音识别")
    # 2) 存音频拿公网 URL（DashScope 需要拉取）
    file_key = build_file_key(str(user.id), "asr", uuid4, ext)
    await storage.save(file_key, content)
    try:
        audio_url = storage.get_url(file_key)
        text = await transcribe(config.provider,
                                decrypt_secret(config.api_key_encrypted),
                                config.model_name, audio_url)
    finally:
        # 3) 用完即弃删文件（不入库）
        await storage.delete(file_key)
    return success({"text": text})
```

流程要点：

- **取默认 ASR 配置**：`get_default_config_for_type(session, user.id, "asr", "语音识别")`，没配时它抛 `BizError(..., code=2010)`——这就是「未配 ASR 让前端降级」的信号。
- **必须先存储拿 URL**：DashScope 异步接口要的是「可公网访问的音频 URL」（`file_urls`），不能直接传字节，所以音频先 `storage.save` 再 `storage.get_url`。
- **用完即弃**：转写是一次性的，音频不是用户资产，不入库。所以放进 `try/finally`，无论转写成功失败都 `storage.delete` 删掉临时音频，删除失败静默（不影响主结果）。
- 空音频报 `2037`。

### 3.3 连接测试分支（`core/llm/provider.py` 的 `_test_asr`）

模型配置页保存时会「测试连接」。但 ASR 的录音文件识别是异步任务，**没有低成本的 ping 方式**（提交一个真任务既慢又费钱）。所以 ASR 分支只做轻校验：

```python
def _test_asr(_base_url, model_name) -> tuple[bool, str]:
    if not model_name:
        return False, "请填写模型名（如 paraformer-v2 / whisper-1）"
    return True, "配置已保存（语音识别将在发送语音时验证）"
```

只校验模型名已填，真实可用性推迟到「真正发语音」时验证。`test_connection` 在 `type_ == "asr"` 时直接走这个分支，不发网络请求。

### 3.4 中文错误码兜底（2010 / 2030~2037）

转写链路上的失败都映射成明确的中文错误码，前端可据此分别处理（降级 / 提示 / 重试）：

| 错误码 | 含义 | 抛出点 |
|--------|------|--------|
| `2010` | 未配置 ASR 模型（前端据此降级到 Web Speech） | `get_default_config_for_type` |
| `2030` | 暂不支持的 ASR 服务商 | `transcribe` |
| `2031` | API Key 无效或无权限（401/403） | DashScope / Whisper |
| `2032` | 任务提交失败 | DashScope 提交 |
| `2033` | 识别失败（任务 FAILED/CANCELED） | DashScope 轮询 |
| `2034` | 识别超时（轮询超 40 次） | DashScope 轮询 |
| `2035` | 服务连接失败（httpx 错误） | DashScope / Whisper |
| `2036` | 未识别到语音内容（结果为空） | 结果解析 |
| `2037` | 音频为空 | 接口入口 |

`_transcribe_dashscope` / `_transcribe_whisper` 都用 `except BizError: raise` + `except httpx.HTTPError` 的双层捕获：自己抛的业务错原样上抛，网络错误归一成 `2035`，避免把原始英文异常栈丢给前端。

---

## 四、设计取舍（已定决策）

| 决策 | 选择 | 理由 |
|------|------|------|
| 整体方案 | **双路**：A 浏览器 Web Speech（前端免费）+ B 云端 ASR（后端） | 默认免费可用，需要更好质量再配云端；后端只管路 B |
| ASR 接入方式 | 复用 `model_configs` 加 **`asr` 类型**，**无迁移** | `type` 是 String 列，加类型只动 schema `Literal`，零迁移 |
| DashScope 调用 | **异步录音文件识别**（提交→轮询→拉 JSON） | Paraformer 录音文件识别是异步接口；需公网音频 URL |
| 音频处理 | 先存储拿 URL，转写后**用完即弃** | DashScope 要公网 URL；音频非用户资产不入库 |
| Whisper 调用 | 下载音频 multipart 同步上传 | OpenAI 接口是同步的，直接传文件 |
| 连接测试 | 仅校验模型名，**不真 ping** | 录音识别异步无低成本 ping，真实可用性发语音时验证 |
| 未配 ASR | 返回 `2010` 让前端降级 | 不强制用户配云端，优雅退回浏览器免费方案 |
| 录音时长 | ≤60s（轮询上限匹配） | 语音输入场景短句为主，控制成本与延迟 |

---

## 五、易踩坑点

1. **DashScope 是异步接口，不能同步等返回**：Paraformer 录音文件识别提交后只给 `task_id`，必须轮询任务状态、成功后再从 `transcription_url` 拉真正的转写 JSON。三段式不能省。轮询要设上限（这里 40 次 ×1.5s ≈ 60s）避免无限等。

2. **音频必须可公网访问**：DashScope 拉的是 `file_urls` 里的 URL，不是上传字节。所以必须先 `storage.save` 再 `storage.get_url` 拿公网地址。如果存储后端给的是内网地址或带鉴权的地址，DashScope 拉不到，转写会失败——部署时要确保 ASR 临时音频的 URL 对云端可达。

3. **转写结果是「URL 套 JSON」两跳**：成功任务的 `results[].transcription_url` 指向的才是真正含文本的 JSON，要再发一次 GET 去拉。直接读任务结果里没有文本。

4. **用完即弃要放 finally**：音频是一次性的临时文件，转写成功或失败都要删，所以 `storage.delete` 放在 `try/finally`，且删除失败要静默（删不掉不应让已拿到的转写结果失败）。

5. **ASR 连接测试别真发请求**：录音识别异步又费钱，没有低成本 ping。`_test_asr` 只校验模型名已填，返回「配置已保存，发语音时验证」。如果在测试里真提交一个任务，会让保存配置变慢且产生费用。

6. **`asr` 类型不需要迁移，但要记得改 `Literal`**：因为 `type` 是 String 列，漏改 `ModelTypeT` 的 `Literal` 会导致 Pydantic 校验把 `asr` 当非法值拒掉——「无迁移」不等于「无改动」，schema 层必须加。

7. **provider 复用 chat 的枚举**：DashScope 用 `qwen`、Whisper 用 `openai`，没有为 ASR 新造 provider。`transcribe` 里按 provider 分流，传了别的 provider 直接抛 `2030`。

---

## 六、面试问答（八股）

**Q1：ASR 语音输入的双路设计是什么？后端负责哪部分？**

双路指两条语音转文字的通道：路 A 是浏览器原生的 Web Speech API（`SpeechRecognition`），纯前端、免费、作为默认和降级方案；路 B 是云端 ASR——用户在模型配置里加一个 `asr` 类型模型（DashScope Paraformer 或 OpenAI Whisper），前端把录音上传到后端，后端调云端服务转写。**后端只负责路 B**：接收音频、存储拿公网 URL、取用户默认 ASR 配置、调云端转写、返回文本、用完即弃删音频。路 A 完全在前端，后端不参与。

**Q2：为什么加 ASR 类型不需要数据库迁移？**

因为 `model_configs` 表的 `type` 列设计成 `String(32)` 普通字符串列，而不是数据库枚举类型。数据库层早就能存任意字符串，新增 `"asr"` 取值对它没有任何 schema 影响。真正的改动只在应用层——把 Pydantic 的 `ModelTypeT = Literal[...]` 加上 `"asr"`，让入参校验放行。这是「扩展点用开放字符串列 + 应用层枚举校验」的好处：增类型零迁移。但要注意「无迁移」不等于「无改动」，漏改 `Literal` 会让 `asr` 被当非法值拒掉。

**Q3：DashScope Paraformer 的调用流程为什么这么绕？**

因为它的录音文件识别是**异步**接口，不是「发音频立即返回文本」。流程三段：① 提交任务——POST 时带 `X-DashScope-Async: enable`，body 传可公网访问的音频 URL，返回 `task_id`；② 轮询任务状态——循环 GET `/tasks/{task_id}`，每 1.5s 一次最多 40 次，等到 `SUCCEEDED`；③ 拉结果——成功任务给的是 `transcription_url`，再 GET 这个 URL 才拿到含文本的 JSON，从 `transcripts[].text` 拼出来。相比之下 Whisper 是同步的，下载音频 multipart 上传就直接返回文本。

**Q4：音频为什么要先存储再转写，转写完又删掉？**

先存储是因为 DashScope 异步接口要的是 `file_urls`——可公网访问的音频 URL，不能直接喂字节，所以必须 `storage.save` 后 `storage.get_url` 拿公网地址传过去。转写完删掉是因为这段音频是一次性的临时数据、不是用户资产，没有保留价值，留着只占存储。删除放在 `try/finally` 里保证成功失败都清理，且删除失败静默——已经拿到的转写文本不该因为删临时文件失败而作废。

**Q5：用户没配 ASR 模型会怎样？**

后端取默认 ASR 配置时走 `get_default_config_for_type(..., "asr", "语音识别")`，没配会抛 `BizError(code=2010)`。前端拿到 2010 就知道「这个用户没开云端 ASR」，据此降级——回退到路 A 浏览器 Web Speech，或提示用户去配置。这样云端 ASR 是可选增强，不配也能用免费的浏览器识别，不强制。

**Q6：ASR 的连接测试为什么不真的发请求验证？**

因为 Paraformer 录音文件识别是异步任务，没有像 chat 的 `max_tokens:1` 那样的低成本 ping——真要验证就得提交一个完整识别任务，既慢又产生费用，放在「保存配置」这种高频操作里不合适。所以 `_test_asr` 只校验模型名是否填了（如 paraformer-v2 / whisper-1），返回「配置已保存，发语音时验证」，把真实可用性推迟到用户真正发语音的时候。这是对「测试成本 vs 即时反馈」的权衡。

**Q7：转写链路的错误处理是怎么做的？**

每个失败点都映射成明确的中文错误码（2010 未配、2030 不支持的服务商、2031 Key 无效、2032 提交失败、2033 识别失败、2034 超时、2035 连接失败、2036 无内容、2037 空音频），前端可据此分别处理。实现上 `_transcribe_dashscope`/`_transcribe_whisper` 用双层捕获：`except BizError: raise` 让自己抛的业务错原样上抛，`except httpx.HTTPError` 把网络错误归一成 2035，绝不把原始英文异常栈直接抛给前端。轮询设上限防无限等，结果为空也有兜底提示。

**Q8：群聊和单聊的语音输入后端实现一样吗？**

一样。后端的 `POST /chat/transcribe` 只做「音频 → 文字」这一件事，与会话类型无关——它不关心转写结果要填进单聊还是群聊的输入框。前端的 `VoiceInputButton` 是个复用组件，单聊和群聊的工具栏都接它，转写填框逻辑在前端。所以后端只有一个转写接口服务两种场景，没有为群聊单独做 ASR 后端。
