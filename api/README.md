# Comet 后端（api/）

彗记 Comet 的 FastAPI 后端。严格分层：**Controller → Service → Repository → Model/DB**，调用方向单向。横切能力（RAG / 记忆 / Agent / LLM / 存储）放在 `core/` 下按子系统分目录。

---

## 目录

- [目录结构与模块职责](#目录结构与模块职责)
- [模型与 API Key 配置（重点）](#模型与-api-key-配置重点)
- [环境变量说明](#环境变量说明)
- [本地开发](#本地开发)
- [数据库迁移](#数据库迁移)
- [Celery 异步任务](#celery-异步任务)
- [Elasticsearch 中文分词（IK）](#elasticsearch-中文分词ik)
- [接口约定](#接口约定)

---

## 目录结构与模块职责

```
api/
├── app/
│   ├── config.py            # pydantic-settings 配置，全部读自环境变量
│   ├── main.py              # FastAPI 入口（create_app + lifespan：启动自动跑 DB 迁移 + 初始化 ES 索引 / Neo4j schema）
│   ├── celery_app.py        # Celery 多队列 + beat 定时配置
│   │
│   ├── controllers/         # 【路由层】只做路由、入参校验、调 service、包装响应
│   │   ├── auth_controller.py          # 注册/登录/刷新/登出/我/改密
│   │   ├── model_config_controller.py  # 模型配置 CRUD + 测试连接 + 设默认
│   │   ├── document_controller.py      # 文档上传/网页导入/列表/详情/重试/删除/检索
│   │   ├── image_controller.py         # 图片上传/列表/详情/删除/检索
│   │   ├── tag_controller.py           # 标签 列表/改名改色/合并/删除
│   │   ├── memory_controller.py        # 主动记住/画像/检索/社区/图谱/时间线/记忆巩固
│   │   ├── chat_controller.py          # 会话 CRUD + SSE 流式问答 + 传图 + 消息反馈/重新生成 + 语音转写
│   │   ├── group_chat_controller.py    # 群聊：建群 + 成员 + 多 Agent SSE 流式（v0.0.3）
│   │   ├── conversation_share_controller.py # 对话分享：建/列/取消 + 无鉴权公开页（v0.0.3）
│   │   ├── agent_config_controller.py  # Agent 提示词/温度/工具开关/主动召回/跨会话
│   │   ├── agent_persona_controller.py # 对话人格（角色卡）CRUD + 切换生效（v0.0.3）
│   │   ├── skill_controller.py         # Skills 技能 CRUD + 内置模板 + 提示词优化（v0.0.3）
│   │   ├── knowledge_base_controller.py # 多知识库管理 + 检索开关（v0.0.3）
│   │   ├── tool_controller.py          # 内置工具配置（注册中心 + 开关）
│   │   ├── mcp_controller.py           # MCP Server 配置 + 工具发现/测试
│   │   ├── emotion_controller.py       # 当前情绪画像 / 趋势 / 记录 / 分布
│   │   ├── music_controller.py         # 音乐推荐 + 曲库 CRUD + 上传 + 音源解析 + 咪咕搜索
│   │   ├── research_controller.py      # 深度研究 SSE 流式 + 列表/详情/删除/save-to-kb + 报告分享/导出(v0.0.4)
│   │   ├── agent_task_controller.py    # 定时任务 CRUD + 运行历史 + 立即运行 + 未读红点(v0.0.4)
│   │   ├── notify_controller.py        # 消息推送渠道 CRUD + 测试推送(v0.0.4)
│   │   ├── trace_controller.py         # 执行轨迹列表/详情/成本聚合(v0.0.5)
│   │   ├── search_controller.py        # 全局搜索
│   │   ├── favorite_controller.py      # 收藏夹
│   │   ├── dashboard_controller.py     # 统计概览 + 记忆趋势 + 每日回顾 + Loop 健康度 + 成本卡
│   │   ├── file_controller.py          # 文件访问 /files/{key}
│   │   └── health_controller.py        # /hello + /health（四存储连通性）
│   │
│   ├── services/            # 【业务层】写业务逻辑，编排 repository 与外部调用
│   ├── repositories/        # 【数据访问层】只做存取，含 neo4j/ 子目录（图谱 Cypher）
│   ├── schemas/             # Pydantic 请求/响应模型
│   ├── models/              # SQLAlchemy ORM 模型（users / model_configs / documents / images /
│   │                        #   tags / memories / conversations / messages / agent_configs /
│   │                        #   favorites / daily_reviews / message_feedbacks / tool_configs /
│   │                        #   mcp_servers / emotion_records / emotion_profiles / songs /
│   │                        #   research_reports / agent_tasks / report_shares / notify_channels(v0.0.4)
│   │                        #   loop_runs / loop_iterations / agent_traces / agent_spans /
│   │                        #   memory_corrections(v0.0.5)）
│   │
│   ├── core/                # 【横切基础设施】
│   │   ├── response.py      #   统一响应 success()/fail()
│   │   ├── exceptions.py    #   BizError + 全局异常处理
│   │   ├── security.py      #   JWT / bcrypt 密码 / Fernet 加密
│   │   ├── dependencies.py  #   通用依赖（get_current_user 等）
│   │   ├── logging.py       #   日志（轮转 + 敏感过滤）
│   │   ├── request_context.py  # request_id 中间件
│   │   ├── llm/             #   LLM 客户端与工厂
│   │   │   ├── client.py    #     LLMClient：裸 httpx 调 OpenAI 兼容接口（embed/chat/vision/rerank）
│   │   │   ├── chat_model.py#     基于 langchain-openai 的 ChatOpenAI 工厂（Agent 用）
│   │   │   ├── provider.py  #     provider 默认 base_url + 连接测试
│   │   │   └── resolver.py  #     按用户默认配置构建 LLMClient
│   │   ├── rag/             #   知识库检索
│   │   │   ├── parser.py    #     PDF/Word/MD/TXT/HTML 解析
│   │   │   ├── chunker.py   #     父子分块（tiktoken）
│   │   │   ├── es_index.py  #     comet_chunks 索引（IK 分词 + 向量）
│   │   │   ├── es_store.py  #     bulk_index / delete / update_tags
│   │   │   ├── search.py    #     混合检索（向量 + BM25 融合 + 可选 rerank + 父块上下文）
│   │   │   ├── classifier.py#     AI 自动分类打标签
│   │   │   ├── image_describe.py # 图片多模态描述/OCR/物体/场景
│   │   │   └── web_crawler.py   # 网页正文抽取（含 SSRF 防护）
│   │   ├── memory/          #   记忆系统（按流水线阶段分目录）
│   │   │   ├── ontology.py  #     受控词表（13 类实体 + 13 谓词）
│   │   │   ├── graph_models.py / graph_schema.py  # 图节点边模型 + Neo4j 约束/索引
│   │   │   ├── preprocessing/   # 分块 + 原子陈述抽取
│   │   │   ├── extraction/      # 三元组萃取 + 向量化 + 去重 + 编排落图（事件萃取）
│   │   │   ├── retrieval/       # 图谱混合检索（向量 + 全文 + 邻居遍历）
│   │   │   ├── clustering/      # 标签传播 LPA 社区聚类
│   │   │   └── prompts/         # jinja2 提示词模板（纯中文）
│   │   ├── agent/           #   智能问答 Agent（方案B）+ Loop Engineering + Tracing
│   │   │   ├── tools/       #     工具体系：注册中心 + 知识库/记忆/联网/内置工具 + MCP 适配
│   │   │   ├── web_search.py#     联网搜索（千帆 / tavily）
│   │   │   ├── orchestrator.py # 强模型 function calling + 弱模型 ReAct 降级
│   │   │   ├── research/    #     深度研究引擎(规划/检索/逐源提炼/反思/大纲/分节写作/汇总)(v0.0.4)
│   │   │   ├── loop/        #     Verifier Loop 自闭环质量保障(controller/verifier/rubric/repair/policy/store/models)(v0.0.5)
│   │   │   ├── tracing/     #     全链路可观测(tracer/span_recorder/pricing/otel_attrs/models)(v0.0.5)
│   │   │   └── prompts/     #     ReAct + 提示词优化器 + research/loop 各 prompt 模板
│   │   ├── emotion/         #   情绪记忆（valence-arousal）
│   │   │   ├── ontology.py  #     13 类主情绪 + 参考坐标词表
│   │   │   ├── analyzer.py  #     LLM 单轮情绪分析（重试 + 健壮解析 + 中性兜底）
│   │   │   ├── aggregator.py#     最近 N 条滚动聚合为当前画像
│   │   │   └── prompts/     #     情绪抽取模板
│   │   ├── music/           #   情绪化音乐推荐
│   │   │   ├── migu_client.py #   咪咕搜索 / listenSong 取免费直链 / 歌词
│   │   │   ├── mood_tagger.py #   LLM 给歌标 valence/arousal/标签
│   │   │   ├── recommender.py #   情绪距离 + 偏好歌手 打分排序
│   │   │   └── prompts/     #     歌曲情绪标注模板
│   │   └── storage/         #   文件存储抽象（本地 LocalStorage / 阿里云 OssStorage + 工厂）
│   │
│   ├── tasks/               # Celery 异步任务
│   │   ├── parse.py         #   文档解析全流程
│   │   ├── image.py         #   图片处理全流程
│   │   ├── memory.py        #   记忆萃取
│   │   ├── emotion.py       #   对话情绪分析 + 画像刷新
│   │   ├── music.py         #   歌曲处理（补封面歌词 + 情绪标注 + 音源验证）
│   │   └── beat.py          #   定时：每日回顾 / 全量社区聚类 / 记忆巩固
│   │
│   └── db/                  # 四存储连接：postgres / elastic / neo4j / redis（含连接池配置）
│
├── migrations/              # Alembic 迁移
├── run.py                   # 本地启动入口
├── pyproject.toml           # 依赖（uv 管理）
├── Dockerfile
└── .env.example
```

调用方向（严格单向）：`controller → service → repository → model/db`。controller 不写业务逻辑，repository 不写业务规则，业务编排集中在 service / 流水线 orchestrator。

---

## 模型与 API Key 配置（重点）

Comet 不在 `.env` 里写任何 LLM 的 API Key。**所有模型与其 API Key 都由登录用户在前端「模型配置」页动态添加**，按用户隔离、存进数据库（`model_configs` 表）。这样多用户各用各的 Key，互不可见。

### 模型类型（type）

每条配置归为一种类型，不同功能取对应类型的「默认」配置使用：

| type | 作用 | 何时必须 |
|------|------|----------|
| `chat` | 对话/问答、记忆萃取、社区命名、每日回顾、AI 打标签 | **必须**（问答与记忆萃取依赖） |
| `embedding` | 文本/实体向量化，知识库与记忆检索的向量召回 | **必须**（不配则无法检索） |
| `multimodal` | 多模态看图：图片描述/OCR、对话传图问答、群聊看图 | 用到图片功能时需要 |
| `rerank` | 检索结果重排序，提升相关度 | 可选 |
| `websearch` | 联网搜索工具（对话联网开关） | 可选 |
| `asr` | 语音识别：对话/群聊语音输入转文字（DashScope Paraformer / OpenAI Whisper）（v0.0.3） | 可选（不配走浏览器免费识别） |

### Provider（供应商）

对话/向量/重排类全部走 **OpenAI 兼容协议**，差异只在 `base_url`：

| provider | 默认 base_url |
|----------|---------------|
| `openai` | https://api.openai.com/v1 |
| `qwen`（通义千问） | https://dashscope.aliyuncs.com/compatible-mode/v1 |
| `doubao`（豆包/火山方舟） | https://ark.cn-beijing.volces.com/api/v3 |
| `deepseek` | https://api.deepseek.com |
| `zhipu`（智谱） | https://open.bigmodel.cn/api/paas/v4 |

联网搜索（`websearch` 类型）provider：`qianfan`（百度千帆 AI 搜索）/ `tavily`。

> 推荐组合：对话 `deepseek` + `deepseek-chat`，Embedding `zhipu` + `embedding-3`（维度 1024）。

### 能力标记（capability）

`chat` 配置可勾选能力，决定问答时的工具编排路径：

- `function_call`：模型支持原生 function calling → 走 LangChain 原生工具调用（强模型路径，推荐勾上）。
- 不勾：走 ToolOrchestrator 的 ReAct 提示词模拟（弱模型降级路径）。
- `vision`：标记多模态能力。

### API Key 怎么存、怎么用（安全）

1. 用户在前端填入明文 API Key → 后端用 **Fernet 对称加密**后存入 `model_configs.api_key_encrypted`（`core/security.py` 的 `encrypt_secret`）。
2. 接口返回时只给**掩码**（`mask_secret`，仅露尾 4 位），永不返回明文。
3. 实际调用 LLM 时由 `decrypt_secret` 解密（`core/llm/resolver.py` 按用户默认配置构建客户端）。
4. 加密用的密钥是 `.env` 里的 **`FERNET_KEY`**——这是**唯一**需要你在服务器配置的密钥，且**一经生成不可更改**（改了之前加密的所有 Key 都解不开）。务必妥善保存、不要进 git。
5. 「测试连接」会用填入的 Key 发一个最小请求验证可用性（`core/llm/provider.py`），通过后再「设为默认」。

> 简言之：`.env` 里只放 `FERNET_KEY`（加密用）和 `JWT_SECRET`（登录用）这两个系统密钥；各家 LLM 的 API Key 都走前端配置、加密入库。

---

## 环境变量说明

完整模板见 `.env.example`。关键项：

| 变量 | 作用 | 备注 |
|------|------|------|
| `JWT_SECRET` | 登录令牌签名密钥 | **必改**，随机长字符串 |
| `FERNET_KEY` | API Key 加密密钥 | **必改且不可变**，用下方命令生成 |
| `POSTGRES_*` | 业务库连接 | 默认 localhost:5432 |
| `ES_HOST` | Elasticsearch 地址 | 默认 http://localhost:9200 |
| `NEO4J_URI/USER/PASSWORD` | 记忆图谱连接 | 默认 bolt://localhost:7687 |
| `REDIS_URL` / `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | 缓存与队列 | Redis 不同 db |
| `STORAGE_BACKEND` | 文件存储后端 | `local`（默认）或 `oss` |
| `OSS_*` | 阿里云 OSS 配置 | `STORAGE_BACKEND=oss` 时填 |
| `EMBEDDING_DIMS` | 向量维度 | 固定 `1024`，需与 Embedding 模型一致 |
| `RAG_DOCLING_ENABLED` | 是否启用复杂 PDF 的 Docling 路由 | 默认 `true`，普通 PDF 仍走 PyMuPDF |
| `RAG_DOCLING_DO_OCR` | Docling 是否启用 RapidOCR | 默认 `true`，固定使用 ONNXRuntime |
| `RAG_DOCLING_CACHE_DIR` | Docling 离线模型目录 | 本地默认 `./storage/docling-models`；容器内 `/app/storage/docling-models` |
| `DB_POOL_*` / `ES_MAX_*` / `NEO4J_MAX_POOL_SIZE` | 各存储连接池 | 一般不用动 |

生成 `FERNET_KEY`：

```bash
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

---

## 本地开发

需先用根目录 `docker compose` 起好 PostgreSQL / ES / Neo4j / Redis 四个存储。

```bash
# 1. 装依赖（自动创建 .venv）
uv sync

# 2. 准备环境变量
cp .env.example .env        # Windows: copy .env.example .env
# 编辑 .env，至少改 JWT_SECRET 和 FERNET_KEY

# 3. 建表
uv run alembic upgrade head

# 4. 启动
uv run python run.py
```

验证：

- `GET http://localhost:8000/api/hello` → 欢迎信息
- `GET http://localhost:8000/api/health` → 四存储连通状态

代码自检：`uv run ruff check .`

### Docling 离线模型

Docling 模型约 564 MB，其中多个权重文件超过 GitHub 单文件 100 MB 限制，已通过 `.gitignore` 排除，不能随代码仓库发布。首次部署需要在宿主机准备 `api/storage/docling-models`，之后该目录会通过 Compose 挂载到 API 与 Worker，`git pull`、重建镜像和重启容器不会删除它。

服务器能访问 Hugging Face 时，可在项目根目录执行一次：

```bash
docker compose run --rm worker docling-tools models download \
  layout tableformer rapidocr \
  -o /app/storage/docling-models
```

服务器不能访问 Hugging Face 时，在可联网机器下载后，将完整目录复制到服务器的 `api/storage/docling-models`。不要只复制单个 `model.safetensors`。模型准备完成后重新构建并启动：

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build api worker
```

---

## 数据库迁移

改了 `models/` 下的 ORM 后：

```bash
uv run alembic revision --autogenerate -m "说明"   # 生成迁移脚本
# 检查 migrations/versions/ 下新生成的脚本是否符合预期
uv run alembic upgrade head                          # 应用
```

> 新建 model 后要在 `models/__init__.py` 注册导入，否则 autogenerate 检测不到。
> `alembic.ini` 保持纯 ASCII（Windows GBK 读取，中文会报错）。
> 加非空列时记得先 `server_default` 回填存量行、再 `alter_column` 清除默认，否则存量数据迁移失败。

### v0.0.3 新增表 / 字段

- `knowledge_bases`（多知识库）+ `documents`/`images` 加 `kb_id`；`knowledge_bases` 加 `chat_enabled`。配套存量回填脚本：`uv run python -m app.db.backfill_kb`(建默认库 + 归入存量资料 + 回填 ES chunk 的 kb_id)。
- `agent_personas`（对话人格/角色卡）；`agent_configs` 加 `show_avatar` / `enable_active_recall` / `enable_cross_session`。
- `skills`（技能）+ `enabled` 列。
- `conversation_shares`（对话分享，含头像/快照 data URL 列）。
- `conversations` 加 `is_group` / `member_persona_ids` / `enable_tools`，`messages` 加 `sender_persona_id`（群聊）。
- `daily_reviews` 加 `care`（AI 主动关心）。
- ASR 语音识别复用 `model_configs`，`type` 新增 `asr` 取值（String 列，**无迁移**）。
- 反思引擎的 `Insight` 节点在 **Neo4j**（非 PG），由启动时图 schema 幂等创建,无 Alembic 迁移。

### v0.0.4 新增表 / 字段

- `research_reports`(深度研究报告,迁移 `979c6e3c897f`)+ `agent_tasks`(定时任务,迁移 `e004fbfb8ac6`)。
- `report_shares`(报告公开分享,迁移 `9d2abf6b960b`);`users` 加 `briefing_seen_at`(任务中心未读红点,迁移 `45e5059b4825`)。
- `notify_channels`(消息推送渠道:Server酱 / 企微 / 钉钉 / webhook,target 字段 Fernet 加密)+ `agent_tasks.notify_enabled`(迁移 `2628f0e24602`)。
- `agent_configs.human_mode`(真人对话模式全局开关,迁移 `bf7ad4190462`)。

### v0.0.5 新增表 / 字段

- **Verifier Loop**:`loop_runs` + `loop_iterations`(迁移 `7a3c4d5e6f01`),`model_configs.type` 加 `verifier` 取值(无 schema 迁移,Literal 扩展)。
- **Tracing + 成本核算**:`agent_traces` + `agent_spans`(迁移 `6727223d45f9`),span 属性 JSONB 兼容 OpenTelemetry GenAI 规范字段名。
- **记忆审查与人类反馈**:`memory_corrections`(迁移 `b8d195cf3e7a`);Neo4j Entity 加动态属性 `human_verified`(无 schema 变更)。

> 后端启动时会自动执行 `alembic upgrade head`(`app/db/migrate.py`,在 lifespan 里)——本地首次仍建议手动跑一次确认无误。

---

## Celery 异步任务

耗时操作（文档解析、记忆萃取、情绪分析、歌曲处理、社区聚类）走异步队列，接口立即返回。

队列规划：`parse`（解析 / 图片 / 歌曲处理）、`memory`（记忆萃取 / 情绪分析）、`beat`（定时：每日回顾 / 全量聚类 / 记忆巩固 / 定时任务调度心跳）、`research`（定时任务的深度研究执行，重活独立队列，避免堵住心跳）、`default`。

```bash
# Worker（Windows 必须 --pool=solo）
uv run celery -A app.celery_app.celery_app worker -l info -Q default,parse,memory,beat,research --pool=solo

# Beat 定时（每日 22:00 回顾、03:00 全量聚类、04:00 记忆巩固）
uv run celery -A app.celery_app.celery_app beat -l info
```

> Linux / macOS 去掉 `--pool=solo`，用 `--concurrency=N` 提并发。
> `research` 队列与 `beat`（调度心跳）分开：心跳轻量不可被堵，研究是重活。线程/prefork 并发≥2 时二者可并存；Windows `--pool=solo` 单进程串行，可再起一个 `-Q research` 的 worker 让心跳独立。
> 新增/改动 `tasks/` 下的任务后需重启 worker 才会加载。

---

## Elasticsearch 中文分词（IK）

知识库 BM25 全文检索依赖 IK 中文分词，否则中文按单字切，效果差。ES 镜像基于官方 + `analysis-ik` 构建（见根目录 `docker/es/Dockerfile`）。

首次启用或更新 IK 时重建 ES 容器：

```bash
# 项目根目录
docker compose build elasticsearch
docker compose up -d elasticsearch
```

`comet_chunks` 索引 content 字段用 `ik_max_word`（写入）/ `ik_smart`（查询）。若用旧 mapping 建过，删掉让其重建：

```bash
curl -X DELETE http://localhost:9200/comet_chunks
# 重启后端会自动重建带 IK 的索引
```

---

## 接口约定

- 统一响应：`{ code, message, data }`。成功 `code=0`；业务失败抛 `BizError`，错误提示用**中文**。
- 鉴权：业务接口加 `Depends(get_current_user)`，未登录自动 401。
- 数据隔离：所有业务查询强制带 `user_id` 过滤，防越权。
- API 文档：启动后访问 `http://localhost:8000/docs`（Swagger UI）查看全部接口。
