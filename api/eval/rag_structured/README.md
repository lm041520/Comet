# 结构化 RAG 固定评测集

将 `cases.example.json` 复制为本地评测文件，并为普通 PDF、双栏 PDF、跨页表格和扫描件分别准备固定问题。

每条数据至少包含：

- `query`：验证问题；
- `expected_source_id`：正确文档 UUID；
- `expected_page`：正确页码，可为空。

评测结果使用 `app.core.rag.evaluation.evaluate_retrieval_cases` 计算 Hit@K 和正确页码率。真实文件和含敏感内容的标注数据不得提交到仓库。
