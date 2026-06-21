# Comet 离线评测（eval）

用业界标准指标，**自包含、可复现**地评测 RAG 检索与记忆系统（抽取 / 去重 / 检索）。

> 自带语料和标注、自己写入再评测，**不依赖现有用户数据、不读 app 的模型配置表**——直接填模型 key 就能跑。
> 不进生产镜像（`api/.dockerignore` 已排除 `eval/`），但进 git / 开源供他人复现。

---

## 设计要点

- **独立配置**：`eval/.env.eval` 直接填 embedding/chat/rerank 的 base_url+model+key，用 `LLMClient` 直接建客户端，不依赖系统里建用户/配模型。
- **固定命名空间**：所有评测数据写在 `EVAL_USER_ID`（固定 UUID）名下，与真实用户隔离，可一键清理。
- **写入到评测全闭环**：`setup` 复用 app 真实的分块/向量化/萃取链路把 fixtures 写进 ES/Neo4j（顺带也验证了写入链路），再评测。
- **双输出**：① 数值报告（Markdown 指标表）② 明细（JSON：每题召回了啥/命中没、每段抽了啥 vs gold），看明细可定位问题、调系统策略。

---

## 目录

```
eval/
├── .env.eval.example     模型配置模板（复制为 .env.eval 填 key）
├── eval_config.py        读 .env.eval 建 client + EVAL_USER_ID
├── metrics.py            标准指标：Recall@k/Prec@k/MRR/nDCG、集合P/R/F1、Pairwise F1
├── clients.py            ES 检索变体（纯向量/BM25/混合/+rerank）+ 客户端清理
├── fixtures/             自带测试数据
│   ├── corpus/*.md       知识库语料（写入 ES）
│   ├── dialogues.json    对话（萃取进 Neo4j）
│   └── gold/             标注集 retrieval / memory_retrieval / extraction / dedup
├── pipeline/
│   ├── setup.py          写入：语料→ES、对话→Neo4j（EVAL_USER_ID 名下）
│   └── teardown.py       清理：删 EVAL_USER_ID 的 ES + Neo4j 数据
├── tasks/
│   ├── retrieval.py      RAG 四配置 + 记忆检索
│   ├── extraction.py     抽取 实体级/三元组级 P/R/F1
│   └── dedup.py          去重 Pairwise P/R/F1
├── reporters.py          输出报告 + 明细
├── run_eval.py           ⭐ 总入口
└── results/              报告与明细（git 忽略）
```

## 自带数据集场景

对齐业界标准评测的题型设计，开箱即可跑：

- **RAG 检索**（仿 BEIR / NQ / HotpotQA 开放域问答）：`fixtures/corpus/` 10 篇通用百科（居里夫人、镭、诺贝尔奖、青霉素、长城、珠峰、大熊猫、光合作用、太阳系、长江），`gold/retrieval.json` 22 题，含**单跳**（答案在单篇）与**多跳**（需跨多篇，如「发现镭的科学家获了什么奖」要串起居里夫人↔诺贝尔奖）。
- **记忆系统**（仿 LoCoMo / LongMemEval 多会话个人对话）：`fixtures/dialogues.json` 是同一人设跨多段的个人陈述（上海产品经理、老家成都、复旦新闻系、养布偶猫团子、爱爬山摄影、学日语、喝拿铁、用 iPhone+索尼相机、妹妹林晓在成都）；gold 的抽取三元组**严格使用受控词表谓词**（属于类型 / 位于 / 拥有 / 偏好 / 了解 / 使用 / 关联于…）。

> 想换成贴合自己数据的场景，直接替换 `fixtures/` 下对应文件即可（语料文件名即 `relevant_doc_ids`）。

## 准备

1. 起存储：`docker compose up -d postgres elasticsearch neo4j redis`。
2. 复制 `eval/.env.eval.example` → `eval/.env.eval`，填 embedding（必需）、chat（必需）、rerank（可选）的 key。
3. （可选）把 `fixtures/` 的语料/对话/gold 换成你自己的，更贴合真实数据。

## 运行（在 api/ 目录）

```bash
uv run python -m eval.run_eval                  # 全流程：模型自检 + 写入 + 全部评测（保留数据）
uv run python -m eval.run_eval --reset          # 重跑：先清空旧数据再写入（推荐，记忆写入非幂等）
uv run python -m eval.run_eval --skip-setup     # 数据已写过，直接评测
uv run python -m eval.run_eval --skip-check     # 跳过模型可用性自检
uv run python -m eval.run_eval --only retrieval # 只跑 RAG 检索（retrieval/memory/extraction/dedup）
uv run python -m eval.run_eval --teardown       # 跑完清理评测数据
```

> 正式跑前会先做**模型可用性自检**：分别调用 embedding / chat / rerank 确认连得通（embedding 还会校验维度是否与 ES 索引一致），不通的必需模型直接中止、rerank 不通则自动跳过其对比列，避免灌了一半数据才发现 key/url 写错。
> 全程带**进度日志**（写入第几篇语料 / 第几段对话萃取、评测第几题），方便看卡在哪一步。

结果在 `eval/results/`：`report-时间.md`（指标表）+ `details-时间.json`（逐条明细）。

## 指标

| 任务 | 指标 |
|------|------|
| RAG 检索（四配置）| Recall@k、Precision@k、MRR、nDCG@k |
| 记忆检索 | Recall@k、Precision@k、MRR、nDCG@k |
| 三元组抽取 | 实体级 / 三元组级 Precision、Recall、F1 |
| 实体去重 | Pairwise Precision、Recall、F1 |

## 诚实声明

均为**小规模自建 gold 集**的离线自测，非大规模公开 benchmark。简历/汇报请如实标注样本规模与评测方式。
