# 群聊（多 Agent）— 设计与八股（后端）

> V0.0.3 压轴特性。让多个「角色卡」在同一个会话里像微信群一样对话：用户发一句话，由一个「主持人」LLM 智能判断该谁接话、按什么顺序发言，角色之间还能互相附和或反驳；可选开启群级工具（知识库/记忆/联网/MCP）、支持带图多模态看图发言、并能快照分享。本篇只讲后端。

---

## 一、功能定位与需求

把单 Agent 的一对一对话，升级为「一对多角色」的群聊协作：

- **多角色卡群聊**：一个群聊会话挂 2~5 个角色卡（persona），每个角色有自己的人设 `system_prompt` 和头像，用各自的口吻发言。
- **主持人调度**：用户每发一句话，先由一个「主持人」LLM 根据用户发言和各角色人设，决定本轮哪些角色发言、以及发言顺序（一般 1~3 个，避免每轮全员刷屏）。
- **@ 指定**：用户消息里 `@某角色名` 时跳过主持人，只让被点名的角色回复。
- **群级工具开关**：`enable_tools` 全群统一（默认关）。开启后每个角色发言走单聊那套工具编排（function calling / ReAct），能查知识库、记忆、联网、MCP。
- **带图多模态**：用户可随消息带图，每个角色用多模态模型看图发言；当模型支持 function calling 时可「边看图边调工具」（如发一张股票图，各角色联网查实时行情再分析）。
- **可分享**：群聊会话复用对话分享能力，快照扩展多发言人（每条消息带 `sender_name` / `sender_avatar`）。

与单聊（`ChatService`）的本质差异：群聊上下文是**多方**的、需要**主持人调度**、要**逐角色冒泡**，因此单独建 `GroupChatService` 与 `core/agent/group_chat.py`，不与单聊混在一起。群聊默认不做记忆萃取（纯人设对话）。

---

## 二、数据模型与迁移

群聊**复用** `conversations` / `messages` 两张表，不另起新表，仅扩列。会话列表、消息列表、改名、删除全部沿用单聊的会话接口。

### 2.1 模型字段（`api/app/models/conversation_model.py`）

`Conversation` 扩三列：

| 字段 | 类型 | 说明 |
|------|------|------|
| `is_group` | `Boolean`，默认 `false`，带索引 | 是否群聊会话。单聊为 `false` |
| `member_persona_ids` | `JSONB`，可空 | 群成员角色卡 id 列表（字符串），仅 `is_group=true` 有意义，**保序** |
| `enable_tools` | `Boolean`，默认 `false` | 群聊是否允许成员调用工具，全群统一 |

`Message` 扩一列：

| 字段 | 类型 | 说明 |
|------|------|------|
| `sender_persona_id` | `UUID`，可空 | 群聊中该消息由哪个角色卡发出；user 消息为空，单聊 assistant 也为空 |

说明：成员列表用 JSONB 存 id 数组而非中间关联表，是因为群成员是「会话创建时勾选的一组角色」，整体读写、不需要按成员反查，JSONB 足够且省一张表 + 省 join。

### 2.2 迁移

两条迁移串联（`8b9b786d9b53` → `31176cc42a17` → `5ca36380b3f0`）：

- **`31176cc42a17`**（conversations 加群聊字段 / messages 加 sender_persona_id）：加 `is_group`、`member_persona_ids`、`is_group` 索引、`sender_persona_id`。
- **`5ca36380b3f0`**（conversations 加群聊工具开关 enable_tools）：加 `enable_tools`。

**关键坑：NOT NULL 列要先 `server_default` 回填存量行，再清除默认。** `is_group` / `enable_tools` 都是非空布尔列，存量会话已有数据，直接加 `nullable=False` 会失败。两条迁移都用了同一手法：

```python
# enable_tools 非空列：先给 server_default 让存量行回填 false，再清除默认
op.add_column(
    'conversations',
    sa.Column('enable_tools', sa.Boolean(), nullable=False, server_default=sa.false()),
)
op.alter_column('conversations', 'enable_tools', server_default=None)
```

先用 `server_default=sa.false()` 让 PostgreSQL 给所有存量行填上 `false`，建列成功后立刻 `alter_column` 把默认清掉——之后新行的默认值由 ORM 层（`default=False`）控制，而不是数据库默认。这样既绕过了「存量行没值」的报错，又保持数据库 schema 干净（不残留 server_default）。

---

## 三、核心实现与代码路径

分层：`group_chat_controller.py`（路由）→ `group_chat_service.py`（业务编排 + SSE 冒泡）→ `core/agent/group_chat.py`（transcript 构造 / 主持人调度 / @ 解析 / 角色流式）+ prompts。

### 3.1 多方上下文：为何用「带发言人前缀的文本 transcript」

> 文件：`api/app/core/agent/group_chat.py` 的 `build_transcript`

单聊的上下文是标准的 `HumanMessage`（用户）/ `AIMessage`（助手）交替。群聊不能这样，因为**对某个正在发言的角色 A 而言，群里别人说的话既不是「自己」也不是「用户」**：

- 别的角色 B 说的话，对 A 来说不是 `AIMessage`（那是 B 不是 A，当成 A 自己说的会让 A 精神分裂）；
- 也不好当 `HumanMessage`（B 不是用户）。

所以群聊统一把多方历史渲染成**一整段带发言人前缀的纯文本**，作为「场景信息」喂给当前发言的角色：

```
【用户】今天大盘怎么样
【价值投资者】我更关注基本面……
【技术派】K 线已经跌破 20 日均线了
```

每条用 `【发言人】内容` 的格式，user 消息发言人记为「用户」。这样无论群里有几个角色、谁说的，对当前发言角色都是清晰、稳定的「这是刚才群里发生的对话」，模型最容易理解、最不容易串角色。`build_transcript` 还做了截断（`MAX_TRANSCRIPT_MESSAGES = 30`），只取最近若干条控制上下文长度。

发言人名字从哪来？每个角色发言落库时把角色名存进 `meta_data.sender_name`（见 3.7），`_history_for_transcript` 直接读这个字段，**不回查角色卡**——因为角色卡可能被改名或删除，以「发言当时的名字」为准更准确。

### 3.2 transcript 一轮内动态累加：实现「接话」

> 文件：`group_chat_service.py` 的 `stream_group_chat`

如果只在轮次开始时构一次 transcript，那本轮里后发言的角色就看不到先发言角色刚说的话，会变成「各说各的」。解决办法是**在一轮内，每个角色说完就把他这句追加进 transcript**：

```python
# 累加进 transcript，使后面的角色能看到这句（接话）
transcript = transcript + f"\n【{member['name']}】{full_text}"
```

于是发言顺序为 [A, B, C] 时：A 看到的是用户那句；B 看到用户那句 + A 刚说的；C 看到用户 + A + B。后面的角色能真正「接住」前面角色的话，对话自然连贯，而不是平行独白。

### 3.3 主持人 LLM 调度 + JSON 健壮解析 + 失败兜底全员

> 文件：`core/agent/group_chat.py` 的 `decide_speakers` + prompt `prompts/group_host.jinja2`

每轮（非 @ 指定时）先用一个**低温、非流式**的主持人模型调度：

```python
host_model, _ = await build_default_chat_model(
    self.session, user_id, temperature=0.3, streaming=False
)
speakers = await decide_speakers(host_model, members, transcript, user_text)
```

`decide_speakers` 的实现要点：

- **喂给主持人的是精简信息**：每个成员只给 `name` + 人设简介（`_persona_brief` 截断到 80 字），transcript 只取最近 `HOST_RECENT_MESSAGES = 8` 条——判断「该谁接话」不需要全量，省 token、降延迟。
- **prompt 约定**（`group_host.jinja2`）：让主持人按用户发言和各角色人设，选 1~3 个最该回应的角色并排序，明确「不必每个都发言、避免全员刷屏」「点名了让他先说」「只能从名单里选、不要编造」，并要求**只输出 JSON**：`{"speakers": ["角色名1", "角色名2"]}`。
- **健壮 JSON 解析**：用 `core/memory/json_utils.parse_json_object`（内部 `json_repair` 修复中文模型常见的非法 JSON），不裸 `json.loads`。
- **过滤 + 去重保序**：解析出的名字要在成员名单里、且去重，防止模型编造或重复。
- **失败兜底全员**：任何异常（LLM 调用失败、解析失败、结果为空）都 `logger.warning` 后**回退为全体成员按定义顺序发言**，保证群聊永不中断。

```python
except Exception as e:
    logger.warning("群聊主持人调度失败，回退全员发言: %s", e)
return member_names
```

### 3.4 @ 指定跳过主持人

> 文件：`core/agent/group_chat.py` 的 `parse_mention`

用户消息含 `@角色名` 时，直接锁定该角色、跳过主持人调度（省一次 LLM 调用、也尊重用户意图）：

```python
mentioned = parse_mention(user_text, member_names)
if mentioned:
    speakers = [mentioned]
else:
    # 主持人调度
```

`parse_mention` 逻辑简单稳健：消息里没有 `@` 直接返回 `None`；有则遍历成员名匹配 `@name`，命中返回该名字。

### 3.5 `_speak` 三路分流

> 文件：`group_chat_service.py` 的 `_speak`

每个角色发言时，根据「是否有图」「是否开工具 + 模型是否支持 function calling」分三路：

1. **纯人设流式**（无图、无工具）：直接 `stream_speaker` 用人设 + transcript 流式产 token。最轻量，对应群级工具关闭的默认场景。

2. **工具编排**（开了工具）：
   - 模型支持 function calling → `run_function_calling`（bind_tools 流式工具循环）；
   - 模型不支持 → `run_react`（prompt 模拟 ReAct 解析 Action/Final）。
   - 工具集由 `build_enabled_tools` 构建（知识库 / 记忆 / 联网 / MCP），知识库范围限定为用户「已启用检索」的库集合（`list_chat_enabled_ids`）。

3. **多模态看图**（带图）：
   - 切到多模态模型（`get_default_config_for_type(..., "multimodal", ...)`），图片经 `_load_image_parts` 读取 → `compress_for_vision` 压缩 → base64 拼成 LangChain `image_url` 内容块（单轮最多 4 张）；
   - 把图随首条 user 消息（`[{type:text}, *image_parts]`）传入；
   - **图 + 工具叠加**：若多模态模型支持 function calling，则走 `run_function_calling`，实现「边看图边调工具」；若不支持 function calling，带图时退化为「看图直答」（ReAct 不便带图）。

`_speak` 是一个异步生成器，统一产出 `{"type": ...}` 事件（`token` / `tool_start` / `tool_result` / `final`），由 `stream_group_chat` 再翻译成 SSE。

### 3.6 角色发言的 system prompt

> 文件：`core/agent/group_chat.py` 的 `build_speaker_messages` + prompt `prompts/group_speaker.jinja2`

每个角色发言的 system prompt = 角色人设 + 群聊场景说明 + 当前 transcript + 当前日期块：

- `group_speaker.jinja2` 在角色人设后追加「场景说明」：告诉它群里有谁、它的身份是谁，要求「只说自己想说的、可以接话/附和/反驳别人、不要复述别人、不要替别人发言、不要加『角色名：』前缀、简洁自然」。
- 末尾用 `context_hint.current_context_block(with_tool_hint=...)` 注入当前日期；开工具时带「时效问题应联网」的引导，解决「问今天的事答旧数据」。

### 3.7 SSE 事件协议

> 文件：`group_chat_service.py`，`_sse(event, data)` 封装

逐角色冒泡，事件序列：

| 事件 | data | 含义 |
|------|------|------|
| `meta` | `{conversation_id, title}` | 会话元信息 |
| `speaker_start` | `{persona_id, name, avatar_url}` | 某角色开始发言 |
| `token` | `{text}` | 当前角色的流式 token |
| `tool_start` | `{tool, query}` | 当前角色开始调用工具（仅开工具时） |
| `tool_result` | `{tool, query, status, text, stats, latency_ms}` | 工具返回 |
| `speaker_end` | `{persona_id, message_id}` | 某角色发言结束（已落库） |
| `done` | `{conversation_id}` | 本轮全部角色发言完成 |
| `error` | `{message}` | 出错 |

落库时机：每个角色发言完，把 `full_text` 连同 `sender_name`（+ 有工具时的 `tool_calls`）写进 `Message.meta_data`，并设 `sender_persona_id`，再发 `speaker_end` 带回 `message_id`。空发言（角色没说出内容）跳过不落库。单角色发言失败 `logger.warning` 后 `continue` 跳过，不影响其余角色（局部降级）。全部发言后 `conv_repo.touch` 更新活跃时间，发 `done`。

### 3.8 建群与成员加载

> 文件：`group_chat_service.py` 的 `create_group` / `list_members` / `_load_members`，`group_chat_controller.py`

- **建群**（`POST /groups`）：`create_group` 校验成员数 `2~5`（`MIN_MEMBERS` / `MAX_MEMBERS`）、每个角色卡归属当前用户（越权校验），id 去重保序，群名缺省取成员名拼接。写 `is_group=true` + `member_persona_ids` + `enable_tools`。
- **成员信息**（`GET /groups/{id}/members`）：`_load_members` 按存储顺序加载角色卡的 `id/name/system_prompt/avatar_url`（头像走 `storage.get_url`，失败仅 warning 不阻断）；角色卡已删除则跳过。
- **流式群聊**（`POST /groups/chat/stream`）：`StreamingResponse` 返回 `text/event-stream`，带 `X-Accel-Buffering: no` 等头防代理缓冲。

---

## 四、设计取舍（已定决策）

| 决策 | 选择 | 理由 |
|------|------|------|
| 群成员数量 | 2~5 个角色 | 太少不成「群」，太多每轮刷屏、token 与延迟爆炸，且主持人难调度 |
| 多方上下文承载 | 带发言人前缀的**文本 transcript** | 角色身份消息（Human/AI 交替）无法表达「第三个角色」，文本前缀对每个发言角色都清晰稳定 |
| 接话实现 | transcript 一轮内**动态累加** | 让后发言角色看到先发言角色刚说的话，自然接话而非平行独白 |
| 调度方式 | 主持人 LLM 决定顺序，失败**兜底全员** | 智能选择该谁接话；容错保证对话不中断 |
| @ 指定 | 跳过主持人，只让被点名角色回 | 尊重用户意图、省一次调度 LLM |
| 群级工具 | `enable_tools` 开关，**默认关、全群统一** | 纯人设群聊轻量；需要时全群一起开，避免逐角色配置复杂度 |
| 带图 | 切多模态模型，每角色看同一组图发言 | 复用单聊多模态能力；支持 function calling 时可边看图边调工具 |
| 记忆萃取 | 群聊**不做** | 群聊是多角色扮演场景，萃取进个人记忆图谱语义不清 |
| 是否新建表 | 复用 conversations/messages 扩列 | 会话/消息列表/删除/分享全部复用，最小改动 |

---

## 五、易踩坑点

1. **AsyncSession 非并发安全**：群聊一轮里多个角色顺序发言，全部复用同一个 `self.session`。SQLAlchemy 的 `AsyncSession` 不是并发安全的，因此角色发言是**串行**的（一个说完再下一个），不能用 `asyncio.gather` 并发跑多个角色——这既是 transcript 接话累加的前提，也避免了 session 并发踩坑。

2. **`is_group` / `enable_tools` 迁移的 server_default 套路**：非空布尔列加列必须先 `server_default=sa.false()` 回填存量行，再 `alter_column(..., server_default=None)` 清除。漏了第一步会因存量行无值而迁移失败；漏了第二步则数据库残留默认值、与 ORM 层默认重复。

3. **角色名映射要以发言时为准**：transcript 的发言人名字从 `meta_data.sender_name` 读，而不是回查角色卡。角色卡可能被改名/删除，回查会导致历史 transcript 名字错乱或丢失。同理主持人调度结果是「名字」，要靠 `name_to_member` 字典映射回成员对象，并过滤名单外的非法名字。

4. **transcript 累加只在内存进行**：本轮的累加是对局部变量 `transcript` 做字符串拼接（用于喂后续角色），与落库是两回事。落库走 `Message`，下一轮重新 `build_transcript` 从历史还原。两者不要混淆。

5. **带图 + 不支持 function calling 的退化**：ReAct 路径不便携带图片内容块，所以「带图 + 模型不支持 function calling」时退化为「看图直答」（丢弃工具能力），不能硬塞进 ReAct。

6. **主持人用低温非流式、发言用高温流式**：主持人要的是稳定的 JSON 决策（`temperature=0.3`，不流式），角色发言要的是自然多样（`temperature=0.8`，流式）。两者用不同实例，别共用一个配置。

---

## 六、面试问答（八股）

**Q1：多 Agent 群聊的上下文怎么设计？为什么不用 HumanMessage / AIMessage 交替？**

单聊上下文是「用户 / 助手」二元，天然对应 `HumanMessage` / `AIMessage`。但群聊是多方：对正在发言的角色 A 来说，别的角色 B 说的话既不是它自己（不能当 `AIMessage`，否则 A 会把 B 的话当成自己说的、人格混乱），也不是用户（不好当 `HumanMessage`）。所以我把多方历史渲染成一整段**带发言人前缀的文本** `【发言人】内容`，作为「场景信息」放进当前角色的 system prompt。每条消息的发言人名字在落库时存进 `meta_data.sender_name`，重建时直接读、不回查角色卡（防改名/删除）。这种文本承载方式对任意数量的角色都清晰稳定，模型最不容易串角色。

**Q2：怎么让角色「接话」而不是「各说各的」？**

关键是 transcript **一轮内动态累加**。一轮里多个角色按主持人给的顺序串行发言，每个角色说完，就把它这句 `\n【角色名】内容` 追加进当前 transcript，再喂给下一个角色。于是顺序 [A,B,C] 时，B 能看到 A 刚说的、C 能看到 A 和 B 的。配合 prompt 里明确「可以附和或反驳前面其他角色刚说的话、不要复述、不要替别人发言」，对话就有了真实群聊的接话感。注意这要求角色串行发言（也正好契合 AsyncSession 非并发安全）。

**Q3：主持人调度的成本和容错怎么权衡？**

成本上：主持人每轮多一次 LLM 调用，所以我给它**低温、非流式、精简输入**——成员只给名字 + 80 字人设简介，transcript 只给最近 8 条，够判断「该谁接话」即可，省 token 降延迟；并且 `@` 指定时直接跳过主持人不调用。容错上：主持人要求只输出 `{"speakers":[...]}` JSON，用 `json_repair` 健壮解析，再过滤掉名单外的名字并去重保序；**任何失败（调用异常 / 解析失败 / 结果为空）都兜底为全体成员按定义顺序发言**，保证群聊永不中断。还限制一般选 1~3 个角色，避免每轮全员刷屏。

**Q4：群聊里多模态看图和工具调用怎么共存？**

群级 `enable_tools` 开关决定是否给角色挂工具。`_speak` 按「有无图 × 是否支持 function calling」分流：纯人设直接流式；带图切多模态模型、把图压缩成 base64 `image_url` 内容块随首条 user 消息传入；当**多模态模型支持 function calling** 时走 `run_function_calling`，就能「边看图边调工具」——比如发一张股票走势图，各角色先看图、再联网查实时行情，结合人设给分析。若模型不支持 function calling，带图时退化为看图直答（ReAct 路径不便携带图片），无图时走 ReAct 文本工具循环。

**Q5：群聊为什么不复用单聊的 ChatService，而是单独建 GroupChatService？**

三点本质差异：① 上下文是多方 transcript 而非二元消息序列；② 需要主持人 LLM 调度发言顺序，单聊没有这一步；③ 要逐角色冒泡 SSE（`speaker_start` / `speaker_end`），一轮产出多条 assistant 消息，每条带 `sender_persona_id`。把这些塞进 ChatService 会让单聊逻辑变臃肿、可读性差。所以群聊单独建 `GroupChatService` + `core/agent/group_chat.py`，但**底层复用** chat_model 工厂、工具构建（`build_enabled_tools`）、编排器（`run_function_calling` / `run_react`）、多模态读图等，避免重复造轮子。数据层也复用 conversations/messages，只扩列。

**Q6：群聊为什么不接记忆萃取，单聊却接？**

单聊是「用户和助手」的真实对话，回答后异步萃取能沉淀用户画像进记忆图谱，语义清晰。群聊是「用户和多个虚构角色卡」的扮演场景，角色说的话是人设演绎、不代表用户事实，把这些萃取进个人记忆图谱会污染画像、语义不清。所以群聊明确不做记忆萃取，保持纯人设对话。

**Q7：一轮里某个角色发言失败了会怎样？怎么保证健壮性？**

单角色发言包在 try/except 里，失败只 `logger.warning` 然后 `continue` 跳过该角色，其余角色照常发言（局部降级，不炸整轮）。空发言（角色没产出内容）也跳过不落库。主持人调度失败兜底全员；模型加载失败 / 群成员不足 / 会话不存在等通过 SSE `error` 事件告知前端。多处遵循「能降级就降级，副作用失败不阻断主流程」的健壮性原则，例如头像 URL 获取失败只 warning、图片读取/压缩失败跳过该图。

**Q8：群成员为什么用 JSONB 数组存而不是中间关联表？**

群成员是「建群时勾选的一组角色卡 id」，使用上总是整体读取（加载全部成员构 transcript、列成员），不需要按成员反向查询「这个角色在哪些群」。用 `member_persona_ids` JSONB 数组直接存在会话行上，读写一次到位、保持成员顺序（影响兜底发言顺序），省一张关联表和 join。代价是不能高效做成员维度的反查，但群聊场景没有这个需求，取舍合理。
