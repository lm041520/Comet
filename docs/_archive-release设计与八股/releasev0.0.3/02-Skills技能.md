# Skills 技能 — 设计与八股（后端）

> V0.0.3 特性，依赖多知识库。技能是比角色卡更聚焦的「任务能力包」：专属任务提示词 + 工具白名单 + 可选绑定知识库 + 轻量配置（快捷开场 / few-shot 示例）打包成一个可挂载的单元。对话时临时挂载一个技能，与当前生效的角色卡**叠加**生效。本篇只讲后端。

---

## 一、功能定位与需求

角色卡定「我是谁」（人设/语气），技能定「我现在做什么专项任务、怎么做、产出什么」。二者正交、可叠加。

- **技能 = 提示词 + 工具白名单 + 绑库 + 配置**：
  - `prompt`：专属任务提示词，对话时叠加在角色卡人设之后。
  - `tool_keys`：工具白名单（内置工具 key 列表）。非空 = 只启用这些工具（覆盖全局工具配置）；空 = 不限定。
  - `kb_id`：可选绑定一个知识库，绑了则该技能的知识库检索范围限定到此库（优先于对话页选的库集合）。
  - `config`：轻量 JSON，含 `quick_prompts`（快捷开场提问）/ `few_shots`（输入→输出示例）。
- **与角色卡叠加**：对话时 `_compose_system_prompt(persona, skill)` 把人设和技能任务拼起来。
- **对话内即时挂载**：发消息时带 `skill_id`，本轮按技能 override 提示词/工具/库范围。
- **内置模板免灌数据**：3 个开箱即用模板（知识库学习 / 股票分析 / 翻译润色）以**代码常量**形式提供，用户「一键添加」复制为自己的技能后可改可删。
- **专属优化提示词**：技能任务提示词有独立的「一键优化」元提示词，聚焦任务（目标/步骤/输出/边界），明确不写人设。
- **`enabled` 显示开关**：控制技能是否在对话页技能选择器里显示，避免技能多了占满入口。

---

## 二、数据模型与迁移

### 2.1 `skills` 表（`api/app/models/skill_model.py`）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `UUID` 主键 | |
| `user_id` | `UUID` FK→users，CASCADE，索引 | 多租户隔离 |
| `name` | `String(64)` | 技能名（如「论文精读」「代码审查」） |
| `description` | `String(256)`，默认 `""` | 一句话简介 |
| `icon` | `String(16)`，默认 `🧩` | emoji 图标 |
| `prompt` | `Text`，默认 `""` | 专属任务提示词，叠加在角色卡人设后注入 |
| `tool_keys` | `JSONB`，默认 `[]` | 工具白名单（内置工具 key）。非空=只用这些；空=不限定 |
| `kb_id` | `UUID` FK→knowledge_bases，`ondelete=SET NULL`，可空，索引 | 绑定的知识库；删库则置空 |
| `config` | `JSONB`，默认 `{}` | `{quick_prompts: [...], few_shots: [{input, output}]}` |
| `enabled` | `Boolean`，默认 `true` | 是否在对话页技能选择器显示 |
| `is_builtin` | `Boolean`，默认 `false` | 是否由内置模板复制而来（标记，用户仍可改删） |
| `sort` | `Integer`，默认 `0` | 列表排序 |
| `created_at` / `updated_at` | `DateTime(tz)` | |

设计要点：

- **`tool_keys` / `config` 用 JSONB**：技能配置是「轻量、结构灵活、整体读写」的——工具白名单是字符串数组，配置是嵌套的快捷提问 + few-shot。塞进 JSONB 比为它们各建关联表省事得多，也不需要按工具/示例反查。
- **`kb_id` 用 `SET NULL` 而非 `CASCADE`**：绑定的知识库被删时，技能本身应保留（只是解绑），置空 `kb_id` 即可，不该连技能一起删。这与 `documents.kb_id` 的 CASCADE 不同——资料属于库，删库连带删；技能只是「引用」了库，删库只解绑。

### 2.2 迁移串联

- **`3b74e7025aee`（create skills table）**：建 `skills` 表（含 user_id CASCADE 外键、kb_id SET NULL 外键、user_id/kb_id 索引）。注意建表时**还没有** `enabled` 列。
- **`8b9b786d9b53`（skill add enabled）**：加 `enabled` 非空布尔列，沿用 server_default 套路：

```python
op.add_column('skills',
    sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()))
op.alter_column('skills', 'enabled', server_default=None)
```

存量技能默认显示（`server_default=true` 回填），建列后清除默认、由 ORM `default=True` 接管。

---

## 三、核心实现与代码路径

分层：`skill_controller.py`（路由）→ `skill_service.py`（CRUD + 内置模板 + 提示词优化）→ `skill_repository.py`（数据访问）。内置模板常量在 `skill_builtins.py`。对话叠加在 `chat_service.py`，优化元提示词在 `core/agent/prompts/optimize_skill_prompt.jinja2`。

### 3.1 与角色卡叠加：提示词拼接

> 文件：`api/app/services/chat_service.py` 的 `_compose_system_prompt`

```python
@staticmethod
def _compose_system_prompt(persona, skill) -> str:
    parts: list[str] = []
    persona_prompt = (persona.system_prompt.strip() if persona else "") or ""
    if persona_prompt:
        parts.append(persona_prompt)                      # ① 角色卡人设打底
    if skill:
        skill_prompt = (skill.prompt or "").strip()
        if skill_prompt:
            parts.append(f"【当前任务能力：{skill.name}】\n{skill_prompt}")  # ② 技能任务叠加
        few_shots = (skill.config or {}).get("few_shots") or []
        examples = []
        for fs in few_shots:                              # ③ few-shot 示例拼进提示词
            inp, out = (fs.get("input") or "").strip(), (fs.get("output") or "").strip()
            if inp and out:
                examples.append(f"示例输入：\n{inp}\n理想输出：\n{out}")
        if examples:
            parts.append("参考以下示例的风格作答：\n\n" + "\n\n".join(examples))
    return "\n\n".join(parts)
```

顺序：人设打底 → `【当前任务能力：xxx】` 段叠加任务提示词 → few-shot 示例。角色卡定身份语气，技能定任务方法，few-shot 稳定输出风格。

### 3.2 工具白名单 override

> 文件：`chat_service.py` 的 `_build_tools`

工具的全局启停由「工具配置页」（`tool_configs`）管理，但挂了技能时，技能的 `tool_keys` 作为**白名单覆盖**全局配置——只启用白名单里的工具，其余全关：

```python
# 技能工具白名单：勾了就只用这些工具（关掉其余干扰），优先级最高
if skill and (skill.tool_keys or []):
    from app.core.agent.tools.base import BUILTIN_REGISTRY
    whitelist = set(skill.tool_keys)
    for key in BUILTIN_REGISTRY:
        overrides[key] = key in whitelist
```

做法是遍历内置工具注册表，把白名单内的工具 override 成开、白名单外的 override 成关。这个 override 优先级最高（在对话页临时开关之上）。语义：技能想专注做某类任务（如「翻译润色」不需要任何工具、「股票分析」只要联网），白名单确保不被无关工具干扰。`tool_keys` 为空时不做白名单限定，沿用全局配置。

### 3.3 知识库范围限定

> 文件：`chat_service.py` 的 `_build_tools`

技能绑了库（`kb_id`）时，知识库检索范围限定到该单库，**优先于**对话页「已启用检索的库集合」：

```python
if skill and skill.kb_id:
    kb_ids = [str(skill.kb_id)]                                   # 技能绑库优先：只检索该库
else:
    kb_ids = await KnowledgeBaseRepository(self.session).list_chat_enabled_ids(user_id)  # 否则用全局启用集合
```

这样「论文精读」技能可以绑定到「论文库」，挂载后检索只命中论文，不被其他库噪声干扰。

### 3.4 内置模板：代码常量免灌数据

> 文件：`api/app/services/skill_builtins.py`

3 个内置模板（`kb_study` 知识库学习 / `stock_analysis` 股票分析 / `translate_polish` 翻译润色）以 Python 常量列表 `BUILTIN_SKILLS` 定义，**不预灌数据库**。每个模板含 key（模板唯一标识，不入库）、name、description、icon、prompt、tool_keys、config。

「一键添加」是把模板**复制**为用户自己的一条 skill 记录（`add_builtin`）：

```python
async def add_builtin(self, user_id, key):
    tpl = get_builtin_skill(key)
    if tpl is None:
        raise BizError("内置技能模板不存在", code=4054, status_code=404)
    skill = Skill(user_id=user_id, name=tpl["name"], ..., is_builtin=True)
    return await self.repo.add(skill)
```

用代码常量而非预灌数据的好处：免迁移、可随版本演进、不污染用户数据（用户不加就不存在）、添加后是用户自己的副本可自由改删。`is_builtin=True` 只是标记来源，用户仍可改可删。

### 3.5 专属任务优化提示词

> 文件：`skill_service.py` 的 `optimize_prompt` + `core/agent/prompts/optimize_skill_prompt.jinja2`

技能任务提示词有独立的「一键优化」，与角色卡人设优化**分开**。元提示词 `optimize_skill_prompt.jinja2` 明确：

- 角色卡管「我是谁」（身份/语气/性格），**你不要写人设**。
- 技能提示词管「任务目标 / 工作步骤 / 输出结构与格式 / 质量与边界要求」。
- 优化原则：忠实原意、任务导向结构、可执行、明确输出、防跑偏防幻觉、不写人设、精简有度、语言一致。
- 输出要求：直接输出正文、不要解释/前后缀、不要代码块包裹。
- 带 3 个 few-shot 示例（口语化→任务结构化 / 含诉求→补全产出格式 / 已较完善→小幅润色）。

服务里用低温（0.4）非流式调默认对话模型，剥离 LLM 可能误加的代码块包裹（`_strip_code_fence`），失败抛 `BizError` 中文提示：

```python
meta_prompt = render_agent_prompt("optimize_skill_prompt.jinja2", raw_prompt=raw)
resp = await model.ainvoke([HumanMessage(content=meta_prompt)])
optimized = self._strip_code_fence(content.strip())
```

### 3.6 对话挂载入口

> 文件：`chat_service.py` 的 `stream_chat`，schema `chat_schema.py`

`ChatStreamRequest.skill_id`（可空 UUID）承载本轮挂载的技能。发消息时：

```python
skill = None
if body.skill_id:
    skill = await self.skill_repo.get(user_id, body.skill_id)   # 带 user_id 校验归属
...
system_prompt = self._compose_system_prompt(persona, skill)
tools = await self._build_tools(user_id, agent, body, citations, stats_holder, skill=skill)
```

技能只在「本轮」生效（挂载是 per-request 的），不改变用户的全局配置。

### 3.7 接口（`skill_controller.py`，前缀 `/skills`）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/skills` | 列出用户全部技能 |
| GET | `/skills/builtins` | 内置模板列表（供「一键添加」前展示） |
| POST | `/skills` | 新建技能 |
| POST | `/skills/builtins/{key}` | 把内置模板复制为用户技能 |
| POST | `/skills/optimize-prompt` | 任务提示词一键优化（专用元提示词） |
| PUT | `/skills/{id}` | 编辑（传啥改啥） |
| DELETE | `/skills/{id}` | 删除 |

`SkillConfig` schema 用 Pydantic 约束 `quick_prompts: list[str]` 与 `few_shots: list[FewShot]`，存进 `config` JSONB。`SkillUpdate` 用 `model_dump(exclude_unset=True)` 部分更新；`kb_id` 传空串/None 表示解绑。

---

## 四、设计取舍（已定决策）

| 决策 | 选择 | 理由 |
|------|------|------|
| 技能 vs 角色卡 | 正交叠加：人设 + 任务 | 人设稳定（我是谁），任务可临时挂载切换（干什么），组合灵活 |
| 配置存储 | `tool_keys`/`config` 用 JSONB | 轻量、结构灵活、整体读写，不需建关联表也不需反查 |
| 工具控制 | `tool_keys` 白名单 override 全局 | 专项任务只用相关工具，屏蔽无关工具干扰；优先级最高 |
| 知识库范围 | 绑库优先于全局启用集合 | 技能可锁定到专属库（如论文精读绑论文库），检索更精准 |
| `kb_id` 外键 | `SET NULL`（非 CASCADE） | 删库只解绑技能、不删技能；技能是引用库不是属于库 |
| 内置模板 | 代码常量 + 一键复制，不预灌库 | 免迁移、随版本演进、不污染用户数据、复制后可自由改删 |
| 提示词优化 | 技能用专属元提示词（聚焦任务、不写人设） | 与角色卡人设优化分工；技能优化不该塑造人格 |
| `enabled` | 控制对话选择器是否显示 | 技能多了不占满对话入口，按需显示 |
| 挂载粒度 | per-request（本轮 `skill_id`） | 技能是临时能力，不改全局配置，随挂随用 |

---

## 五、易踩坑点

1. **`tool_keys` 空 vs 非空语义不同**：非空 = 工具白名单（只用这些、关其余）；空列表 = 不限定（沿用全局工具配置）。不要把「空列表」误当成「禁用所有工具」。

2. **白名单 override 优先级最高**：技能白名单会覆盖对话页的临时工具开关。若用户在对话页开了联网但技能白名单没含 `web_search`，则联网被关——这是有意的（技能专注），但要理解优先级。

3. **`kb_id` 必须用 `SET NULL`**：如果误用 CASCADE，删知识库会连带删掉所有绑定它的技能，这是错的。技能引用库，删库只该解绑（置空）。

4. **`skill_service.py` 的 `from __future__ import annotations`**：该 service 有个方法名叫 `list`，会遮蔽内置 `list`，导致类体执行时 `-> list[dict]` 注解报错。靠 future 注解（延迟求值）规避。这是命名遮蔽的隐坑。

5. **优化提示词要剥代码块**：LLM 优化结果可能误加 ```包裹，`_strip_code_fence` 兜底剥离；optimize 元提示词里也明确要求不要代码块包裹。双保险。

6. **挂载技能要校验归属**：`skill_repo.get(user_id, skill_id)` 带 user_id 过滤，防止挂载别人的技能（越权）。

7. **few-shot 拼进 prompt 会撑长上下文**：few-shot 示例直接拼进 system prompt，示例多/长会显著增加 token。schema 限制了单条示例长度（input 2000 / output 4000），但仍要注意别配太多。

8. **`enabled` 一列两默认**：迁移 `server_default=true` 给存量回填，建列后清除，新建技能走 ORM `default=True`。建表迁移（`3b74e7025aee`）里没有 enabled 列，它是后加的（`8b9b786d9b53`），顺序别搞反。

---

## 六、面试问答（八股）

**Q1：技能和角色卡有什么区别？为什么要拆成两个东西？**

角色卡管「我是谁」——身份、语气、性格、采样温度，是稳定的人设。技能管「我现在做什么专项任务、怎么做、产出什么」——任务目标、工作步骤、输出格式、用哪些工具、检索哪个库，是可临时挂载切换的能力包。拆开是因为这两个维度**正交**：同一个「严谨助理」人设可以挂「论文精读」也可以挂「代码审查」；同一个「论文精读」技能换个人设也能用。对话时 `_compose_system_prompt` 把人设打底、技能任务叠加在后，组合出「以某身份做某任务」。耦合在一起会导致组合爆炸、复用性差。

**Q2：技能的工具白名单是怎么工作的？和全局工具开关什么关系？**

工具的全局启停由工具配置页（`tool_configs`）管。挂了技能且 `tool_keys` 非空时，技能白名单**覆盖**全局：遍历内置工具注册表，白名单内的 override 成开、白名单外 override 成关，且优先级最高（在对话页临时开关之上）。目的是让专项任务只用相关工具——「翻译润色」不需要任何工具，「股票分析」只需要联网。这样能屏蔽无关工具的干扰，让 Agent 更专注。`tool_keys` 为空则不做白名单限定，沿用全局配置。

**Q3：技能绑定知识库后，检索范围怎么变？优先级如何？**

正常对话检索「所有 `chat_enabled=true` 的库集合」（`list_chat_enabled_ids`）。但技能绑了 `kb_id` 时，知识库检索范围**限定到该单库**（`kb_ids=[str(skill.kb_id)]`），优先于全局启用集合。比如「论文精读」技能绑「论文库」，挂载后检索只命中论文，不被其他库噪声污染。这让技能能锁定到专属资料域，检索更精准。绑库用的是多知识库的 `kb_id` 多库过滤机制。

**Q4：内置模板为什么用代码常量而不是预灌数据库？**

代码常量（`skill_builtins.py` 的 `BUILTIN_SKILLS`）有几个好处：① **免迁移**——加/改模板只改代码，不用写数据迁移；② **随版本演进**——模板内容跟着代码版本走，不会出现「老库里灌的旧模板」；③ **不污染用户数据**——用户不点「一键添加」就不存在这条数据，列表干净；④ 「一键添加」是把模板**复制**成用户自己的一条记录（`is_builtin=True` 标记来源），之后用户可自由改删，互不影响。预灌数据库则要处理「模板更新怎么同步到已有用户」「用户改了预灌数据怎么办」等麻烦问题。

**Q5：技能的 `kb_id` 外键为什么用 SET NULL 而不是 CASCADE？**

因为技能和文档对库的关系不同。文档**属于**库（`documents.kb_id` CASCADE）——删库连资料一起删合理。技能只是**引用**了库做检索范围——删库时技能本身应该保留，只是失去那个绑定（解绑），所以用 `ondelete=SET NULL` 把 `kb_id` 置空。如果误用 CASCADE，删一个知识库会连带删掉所有绑定它的技能，用户辛苦配的技能没了，显然错误。

**Q6：为什么技能要单独的提示词优化器，不复用角色卡的？**

因为优化目标不同。角色卡优化是塑造「人设」——身份、语气、性格、口头禅。技能优化是打磨「任务执行」——任务目标、工作步骤、输出结构格式、质量与边界要求，并且**明确不写人设**（那是角色卡的职责）。所以 `optimize_skill_prompt.jinja2` 是专属元提示词，约定优化器聚焦任务导向结构、把模糊要求具体化为可操作步骤、明确产出格式、补防幻觉边界，且不加身份/性格/语气。还配了 3 个针对任务型的 few-shot（口语化→结构化、补全产出格式、小幅润色）。用低温 0.4 求稳定，剥代码块包裹兜底。

**Q7：`skill_service.py` 顶部那行 `from __future__ import annotations` 是干嘛的？**

规避命名遮蔽的坑。这个 service 有个方法叫 `list`（列技能），它会在类作用域里遮蔽内置的 `list`。Python 默认在类体执行时**立即求值**类型注解，于是后面方法的 `-> list[dict]` 注解会去解析 `list`，解析到被遮蔽的方法对象而非内置类型，报错。加 `from __future__ import annotations` 让所有注解变成**延迟求值**（存成字符串、不在定义时执行），就绕过了这个问题。这是「方法名和内置类型/typing 名撞车」时的常见解法。

**Q8：技能是怎么挂载到一次对话里的？会不会改变用户的全局配置？**

挂载是 **per-request** 的：发消息时 `ChatStreamRequest.skill_id` 带上技能 id，`stream_chat` 里用 `skill_repo.get(user_id, skill_id)`（带 user_id 校验归属防越权）取出技能，本轮用它叠加提示词、override 工具白名单、限定知识库范围。技能只影响**这一轮**，不写回 `agent_configs` 等全局配置，下一轮不带 `skill_id` 就恢复正常。这符合「技能是临时挂载的能力、随挂随用」的设计——用户可以这条消息用「翻译润色」、下条消息用「股票分析」，互不残留。
