"""研究检索：四源汇聚（联网搜索+抓正文 / 知识库 / MCP 增强），去重、截断、收集为来源。

设计原则：
- 确定性主干（web + kb）保证一定有干货，不依赖模型决策。
- MCP 增强为锦上添花：强模型 + 已配 MCP 才跑，有界 + 超时，失败整步跳过不拖垮主干。
- 每个外部调用独立 try/except，局部失败降级跳过、记 warning，不炸整条流水线。
- 各函数接受可选 emit 回调（异步），实时上报细粒度进度（搜索/抓取/命中/调用工具），
  供编排器转成活动流推给前端。emit 失败不影响检索。
"""
import asyncio
import uuid
from collections.abc import Awaitable, Callable

from langchain_openai import ChatOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.agent.research.models import (
    SOURCE_KB,
    SOURCE_MCP,
    SOURCE_WEB,
    Source,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

# 进度回调类型：接收一个事件 dict（异步）
EmitFn = Callable[[dict], Awaitable[None]]


async def _emit(emit: EmitFn | None, **fields) -> None:
    """安全地上报一条进度活动（失败不影响检索）。"""
    if emit is None:
        return
    try:
        await emit({"type": "progress", **fields})
    except Exception as e:  # noqa: BLE001
        logger.warning("研究进度上报失败（忽略）: %s", e)


def _short_url(url: str) -> str:
    """取域名做简短展示。"""
    from urllib.parse import urlparse

    try:
        host = urlparse(url).netloc
        return host or url[:40]
    except Exception:  # noqa: BLE001
        return url[:40]


def _truncate(text: str) -> str:
    text = (text or "").strip()
    limit = settings.research_source_truncate_chars
    return text[:limit] + "…" if len(text) > limit else text


# 域名权威性启发式词表（确定性快速打分，无需额外 LLM 调用）。
# 命中即加分；这是经验性优先级，不是黑白名单，未命中的域名仍按充实度参与排序。
_AUTHORITATIVE_TLDS = (".gov.cn", ".edu.cn", ".gov", ".edu", ".ac.cn", ".org.cn")
_AUTHORITATIVE_DOMAINS = {
    # 官方统计 / 权威媒体
    "stats.gov.cn", "people.com.cn", "xinhuanet.com", "cctv.com",
    "caixin.com", "yicai.com", "ce.cn", "gov.cn",
    # 科技 / 学术 / 开发者权威
    "36kr.com", "infoq.cn", "github.com", "arxiv.org", "nature.com",
    "sciencedirect.com", "wikipedia.org", "juejin.cn", "csdn.net",
    "segmentfault.com", "ieee.org", "acm.org",
}
# 内容农场 / 聚合营销号（时效与可信度通常较差，降权但不直接丢弃）
_LOW_QUALITY_HINTS = ("baijiahao.baidu.com", "baidu.com/s", "sohu.com/a")


def _quality_score(source: "Source") -> float:
    """给单个联网来源打质量分（越高越靠前）。

    信号（确定性、无 LLM）：
    - 正文充实度：抓到完整正文比仅剩搜索摘要更可信（封顶 1.0）。
    - 域名权威性：官方/权威 TLD 与知名站点加分，内容农场降权。
    """
    score = 0.0
    n = len(source.content or "")
    score += min(n / 1500.0, 1.0)  # 0~1：正文越长越像完整文章
    dom = _domain_of(source.url or "")
    if dom:
        if any(dom.endswith(t) for t in _AUTHORITATIVE_TLDS):
            score += 1.0
        elif any(dom == d or dom.endswith("." + d) for d in _AUTHORITATIVE_DOMAINS):
            score += 0.7
        if any(h in (source.url or "") for h in _LOW_QUALITY_HINTS):
            score -= 0.8
    return score


def _domain_of(url: str) -> str:
    from urllib.parse import urlparse

    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:  # noqa: BLE001
        return ""


def _rank_and_filter_web(sources: list["Source"]) -> list["Source"]:
    """对联网来源做质量过滤 + 排序：丢弃正文过少的（抓取失败/登录墙），按质量分降序。

    仅作用于联网源；知识库（用户权威资料）/ MCP（专注工具）来源视为可信，不在此过滤。
    排序很关键：下游逐源提炼按顺序处理、要点按相关度截断，优先把好源排前面能提质。
    """
    if not settings.research_source_quality_filter:
        return sources
    kept = [s for s in sources if len(s.content or "") >= settings.research_min_source_chars]
    kept.sort(key=_quality_score, reverse=True)
    return kept


async def get_websearch_config(
    session: AsyncSession, user_id: uuid.UUID
) -> tuple[str, str] | None:
    """取用户默认 websearch 配置 (provider, 明文 key)；无则 None。"""
    from app.core.security import decrypt_secret
    from app.repositories.model_config_repository import ModelConfigRepository

    configs = await ModelConfigRepository(session).list_by_user(user_id, "websearch")
    if not configs:
        return None
    cfg = next((c for c in configs if c.is_default), configs[0])
    return cfg.provider, decrypt_secret(cfg.api_key_encrypted)


# ── A. 联网搜索 + 抓正文（质量主力）──

async def gather_web_sources(
    provider: str, api_key: str, queries: list[str], emit: EmitFn | None = None
) -> list[Source]:
    """多查询联网搜索 → 跨查询按 URL 去重 → 并发抓正文。

    抓不到正文的源用搜索摘要兜底（仍保留为来源），保证有内容可写。
    时效感：自动给查询追加当前年月（用户主题已含具体年份则尊重原查询）。
    """
    from datetime import date

    from app.core.agent.web_search import web_search_structured

    today = date.today()
    year_token = str(today.year)

    def _augment(q: str) -> str:
        # 已包含具体年份（2024~2030 范围），尊重用户原查询
        for y in range(today.year - 2, today.year + 5):
            if str(y) in q:
                return q
        return f"{q} {year_token}年{today.month}月"

    augmented = [_augment(q) for q in queries]

    # 1) 限并发跑各子查询的结构化搜索（防搜索 API 429）+ 失败/限流退避重试
    search_sem = asyncio.Semaphore(settings.research_search_concurrency)

    async def _search(q: str) -> list[dict]:
        async with search_sem:
            last_err: Exception | None = None
            for attempt in range(settings.research_search_retries):
                try:
                    res = await web_search_structured(
                        provider, api_key, q, top_k=settings.research_search_top_k
                    )
                    await _emit(
                        emit, icon="search", ok=True, text=f"已搜索：{q}（{len(res)} 条）"
                    )
                    return res
                except Exception as e:
                    last_err = e
                    status = getattr(getattr(e, "response", None), "status_code", None)
                    if attempt < settings.research_search_retries - 1:
                        # 429（限流）退避更久，其余错误也退避后重试
                        wait = (2.0 if status == 429 else 1.0) * (attempt + 1)
                        await asyncio.sleep(wait)
            logger.warning("研究联网搜索失败（跳过该查询）: q=%s err=%s", q, last_err)
            await _emit(emit, icon="search", ok=False, text=f"搜索失败：{q}")
            return []

    results_per_query = await asyncio.gather(*[_search(q) for q in augmented])

    # 2) 跨查询按 URL 去重（保留首次出现的 title/snippet）
    by_url: dict[str, dict] = {}
    for results in results_per_query:
        for r in results:
            url = (r.get("url") or "").strip()
            if not url or url in by_url:
                continue
            by_url[url] = r
    candidates = list(by_url.values())[: settings.research_fetch_top_n]
    await _emit(
        emit,
        icon="web",
        ok=True,
        text=f"去重后共 {len(candidates)} 个网页，开始抓取正文…",
    )

    # 3) 并发抓正文（限并发 + 单个超时 + 截断），抓不到用摘要兜底
    from app.core.rag.web_crawler import fetch_url_content

    sem = asyncio.Semaphore(settings.research_fetch_concurrency)

    async def _fetch(r: dict) -> Source | None:
        url = r["url"]
        snippet = r.get("snippet") or ""
        title = r.get("title") or url
        async with sem:
            try:
                fetched_title, content = await asyncio.wait_for(
                    fetch_url_content(url), timeout=settings.research_fetch_timeout
                )
                title = fetched_title or title
                body = content
                await _emit(
                    emit, icon="fetch", ok=True, text=f"已读取：{title[:40]}", url=url
                )
            except (TimeoutError, asyncio.TimeoutError):
                logger.warning("研究抓正文超时，用摘要兜底: url=%s", url)
                body = snippet
                await _emit(
                    emit, icon="fetch", ok=False,
                    text=f"抓取超时，改用摘要：{_short_url(url)}", url=url,
                )
            except Exception as e:
                logger.warning("研究抓正文失败，用摘要兜底: url=%s err=%s", url, e)
                body = snippet
                await _emit(
                    emit, icon="fetch", ok=False,
                    text=f"抓取失败，改用摘要：{_short_url(url)}", url=url,
                )
        body = _truncate(body)
        if not body:
            return None
        return Source(index=0, type=SOURCE_WEB, title=title.strip()[:200], content=body, url=url)

    fetched = await asyncio.gather(*[_fetch(r) for r in candidates])
    web_sources = [s for s in fetched if s is not None]

    # 4) 质量过滤 + 排序：丢弃抓取失败/正文过少的源，按权威性与充实度排序
    before = len(web_sources)
    web_sources = _rank_and_filter_web(web_sources)
    dropped = before - len(web_sources)
    if dropped > 0:
        await _emit(
            emit, icon="web", ok=True,
            text=f"质量过滤：保留 {len(web_sources)} 个优质来源（剔除 {dropped} 个低质/抓取失败）",
        )
    return web_sources


# ── B. 知识库检索（用户权威资料）──

async def gather_kb_sources(
    session: AsyncSession,
    user_id: uuid.UUID,
    queries: list[str],
    kb_ids: list[str] | None,
    emit: EmitFn | None = None,
) -> list[Source]:
    """对每个子查询检索知识库，按文档去重聚合为来源。失败返回空。

    避免「自循环」：自动剔除「深度研究报告」库的命中（那是本系统自己产出的旧报告，
    把它当权威源回灌写作会让模型复读旧结论、丢失时效性）。
    """
    from app.core.rag.retrieval import hybrid_search

    # 计算"深度研究报告"库的 id，用于剔除自产报告，避免研究→存库→检索→自循环
    excluded_kb_ids: set[str] = set()
    try:
        from app.repositories.knowledge_base_repository import (
            KnowledgeBaseRepository,
        )

        kb_repo = KnowledgeBaseRepository(session)
        self_kb = await kb_repo.get_by_name(user_id, "深度研究报告")
        if self_kb:
            excluded_kb_ids.add(str(self_kb.id))
    except Exception as e:  # noqa: BLE001
        logger.warning("查询深度研究报告库失败（忽略）: %s", e)

    by_doc: dict[str, dict] = {}
    for q in queries:
        try:
            hits = await hybrid_search(
                session, user_id, q, top_k=settings.research_kb_top_k, kb_ids=kb_ids
            )
        except Exception as e:
            logger.warning("研究知识库检索失败（跳过该查询）: q=%s err=%s", q, e)
            continue
        for h in hits or []:
            sid = h.get("source_id") or h.get("doc_name")
            if not sid:
                continue
            # 过滤自产研究报告（命中 kb_id 在排除集合中），避免知识库自循环
            if excluded_kb_ids and str(h.get("kb_id") or "") in excluded_kb_ids:
                continue
            name = h.get("doc_name") or "知识库文档"
            content = (h.get("content") or "").strip()
            if not content:
                continue
            if sid not in by_doc:
                by_doc[sid] = {"title": name, "parts": []}
            by_doc[sid]["parts"].append(content)

    sources: list[Source] = []
    for info in by_doc.values():
        merged = _truncate("\n\n".join(info["parts"]))
        if merged:
            sources.append(
                Source(index=0, type=SOURCE_KB, title=info["title"][:200], content=merged)
            )
    if sources:
        await _emit(
            emit, icon="kb", ok=True, text=f"知识库命中 {len(sources)} 篇相关资料"
        )
    return sources


# ── C. MCP 增强（专注工具，强模型 + 已配 MCP 才跑）──

async def gather_mcp_sources(
    session: AsyncSession,
    user_id: uuid.UUID,
    topic: str,
    model: ChatOpenAI,
    supports_fc: bool,
    emit: EmitFn | None = None,
) -> list[Source]:
    """用 MCP 工具围绕主题搜集资料：有界工具循环，整步超时，失败整步跳过。

    仅在强模型（支持 function calling）+ 用户已配 MCP 工具时生效。
    """
    if not settings.research_mcp_enabled or not supports_fc:
        return []
    try:
        from app.core.agent.tools.mcp.loader import open_mcp_tools

        async with open_mcp_tools(session, user_id) as mcp_tools:
            if not mcp_tools:
                return []
            await _emit(
                emit, icon="mcp", ok=True, text=f"调用 MCP 工具增强检索（{len(mcp_tools)} 个可用）…"
            )
            return await asyncio.wait_for(
                _run_mcp_loop(model, mcp_tools, topic, emit),
                timeout=settings.research_mcp_timeout,
            )
    except (TimeoutError, asyncio.TimeoutError):
        logger.warning("研究 MCP 增强超时（跳过）: user=%s", user_id)
        return []
    except Exception as e:
        logger.warning("研究 MCP 增强失败（跳过）: user=%s err=%s", user_id, e)
        return []


async def _run_mcp_loop(
    model: ChatOpenAI, mcp_tools: list, topic: str, emit: EmitFn | None = None
) -> list[Source]:
    """绑定 MCP 工具跑有界工具循环，把工具结果收成来源。"""
    from app.core.agent.orchestrator import run_function_calling
    from langchain_core.messages import HumanMessage, SystemMessage

    sys = (
        "你是研究助手。请使用可用的工具，围绕用户的研究主题搜集有价值的事实与数据。"
        "尽量调用与主题最相关的工具，不要编造。搜集到足够信息后直接结束即可，无需长篇回答。"
    )
    messages = [
        SystemMessage(content=sys),
        HumanMessage(content=f"研究主题：{topic}\n请用工具搜集相关资料。"),
    ]
    sources: list[Source] = []
    seen: set[str] = set()
    max_iter = settings.research_mcp_max_iterations
    iter_count = 0
    async for ev in run_function_calling(model, mcp_tools, messages):
        etype = ev.get("type")
        if etype == "tool_start":
            iter_count += 1
            await _emit(
                emit, icon="mcp", ok=True, text=f"调用工具：{ev.get('tool', '')}"
            )
            if iter_count > max_iter:
                break
        elif etype == "tool_result" and ev.get("status") == "success":
            text = (ev.get("text") or "").strip()
            tool = ev.get("tool") or "MCP 工具"
            key = f"{tool}:{text[:80]}"
            if text and key not in seen:
                seen.add(key)
                sources.append(
                    Source(
                        index=0,
                        type=SOURCE_MCP,
                        title=tool[:200],
                        content=_truncate(text),
                    )
                )
        elif etype == "final":
            break
    return sources


def assign_indices(sources: list[Source], start: int = 1) -> list[Source]:
    """给来源统一编引用号（从 start 起，支持多轮检索续编）。"""
    for i, s in enumerate(sources, start):
        s.index = i
    return sources


__all__ = [
    "get_websearch_config",
    "gather_web_sources",
    "gather_kb_sources",
    "gather_mcp_sources",
    "assign_indices",
]
