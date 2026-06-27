# L2 · C-MTEB T2Retrieval

中文 retrieval 业界标杆基准，对照 bge-m3 / bge-large 等公认基线。

## 数据来源

- **HuggingFace 数据集**: [`mteb/T2Retrieval`](https://huggingface.co/datasets/mteb/T2Retrieval)(MMTEB 统一迁移后的新路径,原 `C-MTEB/T2Retrieval` 已只剩 default config)
- **License**: 见数据集仓库 README（用于学术与研究目的）
- 首次运行会通过 `datasets.load_dataset(...)` 下载并缓存到 `api/eval/cache/hf_datasets/`，后续离线可用

## 评测协议

- **指标**: nDCG@10 / Recall@10 / MRR@10（C-MTEB 官方协议，k=10）
- **召回深度**: 50（足够覆盖 top-10）
- **切分**: dev
- **匹配口径**: 按 `source_id == corpus cid` 精确匹配（无名称归一化烦恼）

## 命名空间隔离

- 用独立 `EVAL_USER_ID = eee10000-...-c2`，与 `fixtures/` 的 `eee00000-...-ee` 完全隔离
- 默认跑完自动清理 corpus（避免污染下次跑）；可用 `--keep-corpus` 保留供下次 `--skip-ingest` 直接评测

## 跑法

```bash
# 全量（dev 集 ~ 几千 query）
uv run python -m eval.run_eval --benchmark cmteb-t2

# 小规模快速验证（先跑通流程再上全量）
uv run python -m eval.run_eval --benchmark cmteb-t2 --corpus-limit 1000 --query-limit 50
```

## 输出

- `api/eval/results/report-cmteb-t2-{ts}.md`：指标表
- `api/eval/results/details-cmteb-t2-{ts}.json`：每条 query 的 top-k 召回明细

## 简历话术（待填真实数字）

> 在 C-MTEB T2Retrieval（中文 retrieval 业界标杆）上：
> 混合检索（向量+BM25）nDCG@10 = X，对比纯向量基线 +Y；加 rerank 再 +Z。

## 引用

```bibtex
@misc{xiao2023cpack,
  title={C-Pack: Packaged Resources To Advance General Chinese Embedding},
  author={Shitao Xiao and Zheng Liu and Peitian Zhang and Niklas Muennighoff},
  year={2023},
  eprint={2309.07597},
  archivePrefix={arXiv},
  primaryClass={cs.CL}
}
```
