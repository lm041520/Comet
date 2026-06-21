"""Comet 离线评测包（RAG + 记忆，标准指标）。

不属于应用源码、不进生产镜像（见 api/.dockerignore 排除 eval/），
仅用于本地复现评测：uv run python -m eval.eval_retrieval <user_id>
"""
