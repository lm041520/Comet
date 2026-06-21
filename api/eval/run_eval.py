"""评测总入口：读配置 → 写入数据(setup) → 跑各评测 → 输出报告+明细 → (可选)清理。

用法：
    uv run python -m eval.run_eval                 # 全流程（模型自检 + setup + 全部评测，保留数据）
    uv run python -m eval.run_eval --reset         # 重跑：先清空旧数据再写入评测（推荐）
    uv run python -m eval.run_eval --skip-setup    # 跳过写入，直接评测（数据已写过）
    uv run python -m eval.run_eval --skip-check    # 跳过模型可用性自检
    uv run python -m eval.run_eval --only retrieval # 只跑某项 retrieval/extraction/dedup/memory
    uv run python -m eval.run_eval --teardown      # 跑完清理评测数据

依赖：复制 eval/.env.eval.example 为 eval/.env.eval 并填模型 key（embedding 必需、chat 必需、rerank 可选）。
存储用 docker-compose 起的 PG/ES/Neo4j/Redis。
"""
import argparse
import asyncio

from app.config import settings

from eval import clients, eval_config, reporters
from eval.pipeline.setup import setup_all
from eval.pipeline.teardown import teardown
from eval.tasks import dedup as t_dedup
from eval.tasks import extraction as t_extraction
from eval.tasks import retrieval as t_retrieval


async def _check_models(embed, chat, rerank):
    """跑评测前先确认模型真的能调通，避免灌了一半数据才发现 key/url 错。

    embedding、chat 必须可用（不通直接中止）；rerank 可选，不通则打印告警并返回 None（评测自动跳过 rerank 对比）。
    返回最终可用的 rerank client（可能为 None）。
    """
    print("[check] 模型可用性自检…")

    # embedding（必需）—— 顺带校验维度是否与 ES 索引一致
    try:
        v = await embed.embed_one("评测连通性测试")
    except Exception as e:
        raise RuntimeError(f"embedding 模型不可用（{embed.model_name}）：{e}") from e
    dim = len(v)
    note = ""
    if dim != settings.embedding_dims:
        note = f"  ⚠ 维度 {dim} 与 ES 索引维度 {settings.embedding_dims} 不一致，检索会失败！请改 .env.eval 的 embedding 模型或 EMBEDDING_DIMS"
    print(f"  ✓ embedding 可用（{embed.model_name}，维度 {dim}）")
    if note:
        print(note)

    # chat（必需）
    try:
        txt = await chat.chat([{"role": "user", "content": "回复两个字：可用"}], max_tokens=16)
    except Exception as e:
        raise RuntimeError(f"chat 模型不可用（{chat.model_name}）：{e}") from e
    print(f"  ✓ chat 可用（{chat.model_name}）：{(txt or '').strip()[:20]}")

    # rerank（可选）
    if rerank is None:
        print("  - 未配置 rerank，将跳过 rerank 对比列")
        return None
    try:
        await rerank.rerank("测试查询", ["相关的文档内容", "完全无关的内容"], top_n=2)
        print(f"  ✓ rerank 可用（{rerank.model_name}）")
        return rerank
    except Exception as e:
        print(f"  ⚠ rerank 不可用（{rerank.model_name}），跳过 rerank 对比：{e}")
        return None


async def _run(args) -> None:
    embed = eval_config.embed_client()
    chat = eval_config.chat_client()
    rerank = eval_config.rerank_client()
    only = args.only

    # 0. 模型可用性自检（除非 --skip-check）
    if not args.skip_check:
        rerank = await _check_models(embed, chat, rerank)

    setup_stats = None
    try:
        # 0.5 可选：先清空评测命名空间旧数据（记忆写入非幂等，重跑前清一次更干净）
        if args.reset and not args.skip_setup:
            print("[reset] 清空旧评测数据（ES + Neo4j）…")
            await teardown()
        # 1. 写入（除非 --skip-setup）
        if not args.skip_setup:
            print("[setup] 写入评测语料与记忆…")
            setup_stats = await setup_all(chat, embed)
            print(f"[setup] 完成：{setup_stats}")

        # 2. 各评测
        results: dict = {}
        details: dict = {}

        if only in (None, "retrieval"):
            print("[eval] RAG 检索…")
            results["RAG 检索"], details["RAG 检索"] = await t_retrieval.eval_rag(embed, rerank)
        if only in (None, "memory"):
            print("[eval] 记忆检索…")
            results["记忆检索"], details["记忆检索"] = await t_retrieval.eval_memory(embed)
        if only in (None, "extraction"):
            print("[eval] 三元组抽取…")
            results["三元组抽取"], details["三元组抽取"] = await t_extraction.eval_extraction(chat)
        if only in (None, "dedup"):
            print("[eval] 实体去重…")
            results["实体去重"], details["实体去重"] = await t_dedup.eval_dedup(chat, embed)

        # 3. 输出
        reporters.print_summary(results)
        rpt = reporters.write_report(results, setup_stats)
        det = reporters.write_details(details)
        print(f"\n报告：{rpt}\n明细：{det}")

        # 4. 可选清理
        if args.teardown:
            print("[teardown] 清理评测数据…")
            await teardown()
    finally:
        await clients.close_clients()


def main() -> None:
    p = argparse.ArgumentParser(description="Comet 离线评测（RAG + 记忆）")
    p.add_argument("--skip-setup", action="store_true", help="跳过写入，直接评测")
    p.add_argument("--reset", action="store_true", help="setup 前先清空旧评测数据（推荐重跑时用）")
    p.add_argument("--skip-check", action="store_true", help="跳过模型可用性自检")
    p.add_argument("--teardown", action="store_true", help="跑完清理评测数据")
    p.add_argument("--only", choices=["retrieval", "memory", "extraction", "dedup"],
                   help="只跑某一项")
    asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    main()
