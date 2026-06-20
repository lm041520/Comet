"""问答业务服务：SSE 流式对话（方案B 工具编排）。

流程：加载默认对话模型 + Agent 配置 → 构建工具（知识库/记忆/联网，按开关）
→ 强模型走原生 function calling / 弱模型走 ReAct → 流式产出 token/工具标记/引用
→ 落库 user/assistant 消息（assistant 带引用与工具调用元信息）
→ 回答后异步派发记忆萃取（对话自动萃取）。
"""
import asyncio
import json
import uuid
from collections.abc import AsyncGenerator

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent.orchestrator import run_function_calling, run_react
from app.core.agent.tools import build_enabled_tools, build_enabled_tools_cm
from app.core.realtime import bus
from app.core.llm.chat_model import (
    build_chat_model,
    build_default_chat_model,
    get_default_config_for_type,
    supports_function_call,
)
from app.core.logging import get_logger
from app.core.storage import get_storage
from app.db.postgres import SessionLocal
from app.models.agent_config_model import AgentConfig
from app.models.conversation_model import (
    ROLE_ASSISTANT,
    ROLE_USER,
    Conversation,
    Message,
)
from app.repositories.agent_config_repository import AgentConfigRepository
from app.repositories.agent_persona_repository import AgentPersonaRepository
from app.repositories.conversation_repository import (
    ConversationRepository,
    MessageRepository,
)
from app.repositories.skill_repository import SkillRepository
from app.schemas.chat_schema import ChatStreamRequest

logger = get_logger(__name__)

MAX_HISTORY_TURNS = 20

# 后台生成任务引用集合（防止 create_task 的任务被 GC 提前回收）
_BG_TASKS: set = set()
# 单次写流式缓冲的最小 token 间隔（攒够 N 个 token 才刷一次 Redis，降低写频）
_BUFFER_FLUSH_EVERY = 8


def _compose_with_attachments(user_text: str, attachments: list) -> str:
    """把对话临时附件的全文拼到用户问题前，供模型阅读。

    attachments 元素为 {file_name, text}（schema ChatAttachment 或历史 meta_data）。
    无附件时原样返回。
    """
    if not attachments:
        return user_text
    parts: list[str] = []
    for att in attachments:
        name = att.get("file_name") if isinstance(att, dict) else getattr(att, "file_name", "")
        text = att.get("text") if isinstance(att, dict) else getattr(att, "text", "")
        if not text:
            continue
        parts.append(f"【用户上传的文档「{name}」内容如下】\n{text}\n【文档结束】")
    if not parts:
        return user_text
    return "\n\n".join(parts) + f"\n\n基于以上文档内容，回答我的问题：\n{user_text}"


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class ChatService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.conv_repo = ConversationRepository(session)
        self.msg_repo = MessageRepository(session)
        self.agent_repo = AgentConfigRepository(session)
        self.persona_repo = AgentPersonaRepository(session)
        self.skill_repo = SkillRepository(session)

    @staticmethod
    def _user_meta(attachments: list, image_keys: list[str]) -> dict | None:
        """组装 user 消息的 meta_data：对话附件 + 图片 key（供历史还原与分享）。"""
        meta: dict = {}
        if attachments:
            meta["attachments"] = attachments
        if image_keys:
            meta["image_keys"] = list(image_keys)
        return meta or None

    async def _ensure_conversation(
        self, user_id: uuid.UUID, body: ChatStreamRequest
    ) -> Conversation:
        if body.conversation_id:
            conv = await self.conv_repo.get(user_id, body.conversation_id)
            if conv:
                return conv
        title = body.message.strip()[:20] or "新对话"
        return await self.conv_repo.create(Conversation(user_id=user_id, title=title))

    async def _history_messages(self, conv_id: uuid.UUID) -> list:
        """历史消息转 LangChain 消息（不含 system 与当前问题）。

        当前问题会在主流程单独追加，故这里丢弃末尾那条 user 消息（即本轮刚落库的提问），
        避免当前问题（含附件全文）在 prompt 中重复出现。
        若某条历史 user 消息带对话附件（meta_data.attachments），把附件全文还原进
        该轮 HumanMessage，使后续追问在历史窗口内仍能看到文档内容。
        """
        out: list = []
        history = await self.msg_repo.recent_history(conv_id, MAX_HISTORY_TURNS)
        # 丢弃末尾连续的 user 消息（本轮提问），它由主流程单独追加
        while history and history[-1].role == ROLE_USER:
            history.pop()
        for m in history:
            if m.role == ROLE_USER:
                atts = (m.meta_data or {}).get("attachments") if m.meta_data else None
                content = _compose_with_attachments(m.content, atts or [])
                out.append(HumanMessage(content=content))
            elif m.role == ROLE_ASSISTANT:
                out.append(AIMessage(content=m.content))
        return out

    async def _cross_session_context(
        self, user_id: uuid.UUID, current_conv_id: uuid.UUID
    ) -> str:
        """跨会话上下文：取最近其他会话的标题 + 最后几轮，拼成参考背景块。

        纯 PG 查询（快），失败/无其他会话返回空串。
        """
        try:
            from app.config import settings as _s
            from app.models.conversation_model import ROLE_ASSISTANT, ROLE_USER

            convs = await self.conv_repo.list_by_user(user_id)
            others = [c for c in convs if c.id != current_conv_id][
                : _s.cross_session_max_convs
            ]
            if not others:
                return ""
            blocks: list[str] = []
            for c in others:
                msgs = await self.msg_repo.recent_history(
                    c.id, _s.cross_session_turns_per_conv
                )
                if not msgs:
                    continue
                lines = [f"〔会话「{c.title}」〕"]
                for m in msgs:
                    if m.role == ROLE_USER:
                        lines.append(f"用户：{(m.content or '').strip()}")
                    elif m.role == ROLE_ASSISTANT:
                        lines.append(f"我：{(m.content or '').strip()}")
                blocks.append("\n".join(lines))
            if not blocks:
                return ""
            block = "【最近你还和我聊过（仅供参考，不必主动提起）】\n" + "\n\n".join(blocks)
            if len(block) > _s.cross_session_max_chars:
                block = block[: _s.cross_session_max_chars] + "…"
            logger.info("跨会话上下文注入: user=%s 会话数=%d", user_id, len(blocks))
            return block
        except Exception as e:
            logger.warning("跨会话上下文构建失败（忽略）: user=%s err=%s", user_id, e)
            return ""

    async def _recall_memory(self, user_id: uuid.UUID, query: str) -> str:
        """主动记忆召回：失败不影响对话，返回空串。"""
        try:
            from app.core.llm.resolver import get_optional_client_for_type
            from app.core.memory.retrieval.active_recall import recall_context

            embed_client = await get_optional_client_for_type(
                self.session, user_id, "embedding"
            )
            if embed_client is None:
                return ""
            return await recall_context(
                embed_client=embed_client, user_id=user_id, query=query
            )
        except Exception as e:
            logger.warning("主动记忆召回失败（忽略）: user=%s err=%s", user_id, e)
            return ""

    @staticmethod
    def _compose_system_prompt(persona, skill) -> str:
        """组装 system prompt：角色卡人设 + 技能任务提示词 + few-shot 示例（叠加）。

        角色卡定「我是谁」，技能叠加「我现在干什么专项任务」。两者可组合。
        开启真人模式（persona.human_mode）则再叠加「真人聊天风格」段，让回复口语化、可多气泡。
        """
        parts: list[str] = []
        persona_prompt = (persona.system_prompt.strip() if persona else "") or ""
        if persona_prompt:
            parts.append(persona_prompt)
        if skill:
            skill_prompt = (skill.prompt or "").strip()
            if skill_prompt:
                parts.append(f"【当前任务能力：{skill.name}】\n{skill_prompt}")
            # few-shot 示例拼进提示词，稳定该技能输出风格
            few_shots = (skill.config or {}).get("few_shots") or []
            examples: list[str] = []
            for fs in few_shots:
                if not isinstance(fs, dict):
                    continue
                inp = (fs.get("input") or "").strip()
                out = (fs.get("output") or "").strip()
                if inp and out:
                    examples.append(f"示例输入：\n{inp}\n理想输出：\n{out}")
            if examples:
                parts.append("参考以下示例的风格作答：\n\n" + "\n\n".join(examples))
        return "\n\n".join(parts)

    async def _tool_scope(
        self, user_id: uuid.UUID, body: ChatStreamRequest, skill=None
    ) -> tuple[dict[str, bool], list[str] | None]:
        """计算本轮工具的 overrides（启停覆盖）与知识库检索范围 kb_ids。

        - 对话页本轮临时开关（联网/知识库/记忆）作为 override，优先级最高。
        - 技能 tool_keys 非空 → 工具白名单（只开白名单内的）。
        - 知识库范围：技能绑库优先，否则取用户「已启用检索」的库集合。
        """
        overrides: dict[str, bool] = {}
        if body.enable_knowledge is not None:
            overrides["knowledge_search"] = body.enable_knowledge
        if body.enable_memory is not None:
            overrides["memory_search"] = body.enable_memory
        if body.enable_web_search is not None:
            overrides["web_search"] = body.enable_web_search

        if skill and (skill.tool_keys or []):
            from app.core.agent.tools.base import BUILTIN_REGISTRY

            whitelist = set(skill.tool_keys)
            for key in BUILTIN_REGISTRY:
                overrides[key] = key in whitelist

        from app.repositories.knowledge_base_repository import (
            KnowledgeBaseRepository,
        )

        if skill and skill.kb_id:
            kb_ids: list[str] | None = [str(skill.kb_id)]
        else:
            kb_ids = await KnowledgeBaseRepository(self.session).list_chat_enabled_ids(
                user_id
            )
        return overrides, kb_ids

    async def _build_tools(
        self,
        user_id: uuid.UUID,
        agent: AgentConfig | None,
        body: ChatStreamRequest,
        citations: list[dict],
        stats_holder: dict[str, dict],
        skill=None,
    ) -> list:
        """构建启用的工具列表（无状态 MCP 版本，保留备用）。

        工具启停统一由「工具配置页」(tool_configs) 管理，这里不再读 agent 的工具开关；
        仅把对话页本轮的临时开关（如联网）作为 override 传入，优先级最高。
        """
        overrides, kb_ids = await self._tool_scope(user_id, body, skill)
        return await build_enabled_tools(
            self.session,
            user_id,
            citations,
            overrides,
            stats_holder=stats_holder,
            kb_ids=kb_ids,
        )

    async def stream_chat(
        self, user_id: uuid.UUID, body: ChatStreamRequest, skip_user_message: bool = False
    ) -> AsyncGenerator[str, None]:
        """SSE 流式问答（触发 + 转发模型）。

        生成动作不再跑在本 SSE 连接里，而是派一个独立 session 的后台任务生成（_run_chat_turn_bg），
        通过 Redis 频道广播 token；本连接只「订阅频道并转发」给当前客户端。这样客户端中途断开
        （切页面/关标签）只会停止转发，后台生成照常跑完并落库——回来重拉历史能看到完整回复，
        生成中重连还能续传（见 resume_events）。
        """
        user_text = body.message.strip()
        # 前置 PG 工作（建会话 + 落 user 消息）用「用完即关」的独立 session，
        # 避免请求依赖 session 在整个转发期间被挂着——转发只用 Redis，不占 PG 连接，
        # 客户端断开也不会留下未归还的连接（修 GC 回收连接告警）。
        attachments = [
            {"file_name": a.file_name, "text": a.text} for a in body.attachments if a.text
        ]
        try:
            async with SessionLocal() as session:
                svc = ChatService(session)
                conv = await svc._ensure_conversation(user_id, body)
                cid = str(conv.id)
                title = conv.title
                if not skip_user_message:
                    # AI 主动开场白（今日回顾「聊聊」）：仅新会话首轮，先把开场白作为
                    # assistant 消息落库，使其进入对话历史，模型回复时能接住这个话题。
                    greeting = (body.greeting or "").strip()
                    if greeting and await svc.msg_repo.count(conv.id) == 0:
                        await svc.msg_repo.add(
                            Message(
                                conversation_id=conv.id,
                                role=ROLE_ASSISTANT,
                                content=greeting,
                            )
                        )
                    await svc.msg_repo.add(
                        Message(
                            conversation_id=conv.id,
                            role=ROLE_USER,
                            content=user_text,
                            meta_data=self._user_meta(attachments, body.image_keys),
                        )
                    )
        except Exception as e:
            yield _sse("error", {"message": str(e)})
            return

        yield _sse("meta", {"conversation_id": cid, "title": title})

        # 先建立订阅再触发生成，消除「token 早于订阅而漏收」的竞态
        conv_uuid = uuid.UUID(cid)
        pubsub = await bus.open_channel(cid)
        try:
            # 拿回合锁：若已有同会话生成在跑（用户重复发/并发），不重复触发，只转发现有生成
            if await bus.acquire_turn_lock(cid):
                task = asyncio.create_task(
                    self._run_chat_turn_bg(
                        user_id, conv_uuid, body, attachments, skip_user_message
                    )
                )
                _BG_TASKS.add(task)
                task.add_done_callback(_BG_TASKS.discard)
            # 转发频道事件给本客户端，直到 done/error
            async for sse in self._relay(pubsub, cid):
                yield sse
        finally:
            await bus.close_channel(pubsub, cid)

    async def resume_events(
        self, user_id: uuid.UUID, conv_id: uuid.UUID
    ) -> AsyncGenerator[str, None]:
        """断线重连续传：若该会话正有生成在进行，先补推已生成内容（resume 事件），再续接后续
        token 直到 done/error；没有进行中的生成则发 idle 立即结束。"""
        # 校验会话归属用「用完即关」的独立 session，避免请求依赖 session 在续传期间被挂着
        async with SessionLocal() as session:
            conv = await ConversationRepository(session).get(user_id, conv_id)
        if not conv:
            yield _sse("error", {"message": "会话不存在"})
            return
        cid = str(conv_id)
        buf = await bus.get_stream_buffer(cid)
        pubsub = await bus.open_channel(cid)
        try:
            # 二次确认（订阅后再读一次）：消除「读缓冲→订阅」间隙里生成刚好结束、
            # done 已广播而本订阅错过的竞态。生成结束时是「先清缓冲再发 done」，
            # 故订阅后缓冲若已不在 generating，说明已结束，让前端去重拉历史即可。
            if not (buf and buf.get("status") == "generating"):
                yield _sse("idle", {})
                return
            buf2 = await bus.get_stream_buffer(cid)
            if not (buf2 and buf2.get("status") == "generating"):
                yield _sse("idle", {})
                return
            buf = buf2
            seen = int(buf.get("n", 0))
            yield _sse(
                "resume",
                {
                    "content": buf.get("content", ""),
                    "citations": buf.get("citations", []),
                    "tool_calls": buf.get("tool_calls", []),
                },
            )
            async for sse in self._relay(pubsub, cid, skip_token_before=seen):
                yield sse
        finally:
            await bus.close_channel(pubsub, cid)

    async def _relay(
        self, pubsub, cid: str, skip_token_before: int = 0
    ) -> AsyncGenerator[str, None]:
        """把频道事件转成 SSE 转发给客户端，遇 done/error 结束。

        skip_token_before：续传时跳过序号 < 该值的 token（这些已在 resume 补推的内容里）。
        """
        async for evt in bus.iter_channel(pubsub, cid):
            ev = evt.get("event")
            data = evt.get("data") or {}
            if ev == "_ping":
                yield ": ping\n\n"
            elif ev == "token":
                if int(data.get("i", 0)) < skip_token_before:
                    continue
                yield _sse("token", {"text": data.get("text", "")})
            elif ev == "tool_start":
                yield _sse(
                    "tool_start",
                    {"tool": data.get("tool"), "query": data.get("query", "")},
                )
            elif ev == "tool_result":
                yield _sse("tool_result", data)
            elif ev == "citation":
                yield _sse("citation", {"citations": data.get("citations", [])})
            elif ev == "done":
                yield _sse("done", data)
                return
            elif ev == "error":
                yield _sse("error", data)
                return

    async def _run_chat_turn_bg(
        self,
        user_id: uuid.UUID,
        conv_id: uuid.UUID,
        body: ChatStreamRequest,
        attachments: list[dict],
        skip_user_message: bool,
    ) -> None:
        """后台生成任务：用独立 session 跑问答，逐 token 广播到频道 + 写续传缓冲，
        完成后落库 assistant 消息并派发副作用（记忆/图片/情绪），最后广播 done。

        与发起请求的 SSE 连接解耦：客户端断开不影响本任务，保证生成跑完、落库。
        """
        cid = str(conv_id)
        user_text = body.message.strip()
        full_text = ""
        tool_calls: list[dict] = []
        citations: list[dict] = []
        n = 0

        async def _flush_buffer(status: str = "generating") -> None:
            await bus.set_stream_buffer(
                cid,
                {
                    "content": full_text,
                    "n": n,
                    "citations": citations,
                    "tool_calls": tool_calls,
                    "status": status,
                },
            )

        try:
            async with SessionLocal() as session:
                svc = ChatService(session)
                conv = await svc.conv_repo.get(user_id, conv_id)
                if conv is None:
                    await bus.publish(cid, "error", {"message": "会话不存在"})
                    return
                await _flush_buffer("generating")
                async for ev in svc._generate_events(
                    user_id, conv, body, attachments, citations
                ):
                    etype = ev.get("type")
                    if etype == "token":
                        text = ev["text"]
                        full_text += text
                        await bus.publish(cid, "token", {"text": text, "i": n})
                        n += 1
                        if n % _BUFFER_FLUSH_EVERY == 0:
                            await _flush_buffer("generating")
                    elif etype in {"tool_call", "tool_start"}:
                        tool_calls.append({
                            "tool": ev["tool"],
                            "query": ev.get("query", ""),
                            "status": "running",
                        })
                        await bus.publish(
                            cid,
                            "tool_start",
                            {"tool": ev["tool"], "query": ev.get("query", "")},
                        )
                    elif etype == "tool_result":
                        for item in reversed(tool_calls):
                            if (
                                item.get("tool") == ev["tool"]
                                and item.get("status") == "running"
                            ):
                                item["status"] = ev.get("status", "success")
                                item["stats"] = ev.get("stats") or {}
                                item["latency_ms"] = ev.get("latency_ms")
                                item["preview"] = ev.get("text", "")
                                break
                        await bus.publish(
                            cid,
                            "tool_result",
                            {
                                "tool": ev["tool"],
                                "query": ev.get("query", ""),
                                "status": ev.get("status", "success"),
                                "text": ev.get("text", ""),
                                "stats": ev.get("stats") or {},
                                "latency_ms": ev.get("latency_ms"),
                            },
                        )
                    elif etype == "final" and not full_text:
                        full_text = ev["text"]
                    elif etype == "citation":
                        citations = ev["citations"]
                        await bus.publish(cid, "citation", {"citations": citations})

                full_text = full_text.strip()
                # 落库 assistant 消息（带引用 + 工具调用元信息）
                assistant_msg = await svc.msg_repo.add(
                    Message(
                        conversation_id=conv_id,
                        role=ROLE_ASSISTANT,
                        content=full_text,
                        meta_data={"citations": citations, "tool_calls": tool_calls},
                    )
                )
                await svc.conv_repo.touch(conv_id)
                # 副作用（失败不影响）：记忆萃取派发 / 图片入库 / 情绪分析
                await svc._dispatch_memory(user_id, user_text)
                if body.image_keys:
                    await svc._ingest_chat_images(user_id, body.image_keys)
                if not skip_user_message:
                    svc._dispatch_emotion(user_id, user_text, conv_id, assistant_msg.id)

                # 先清缓冲再广播 done：保证「订阅时缓冲若仍在=done 尚未发出」，
                # 重连方据此不会订到一个已结束、done 已错过的频道而空等（见 resume_events）。
                await bus.clear_stream_buffer(cid)
                await bus.publish(
                    cid,
                    "done",
                    {"conversation_id": cid, "message_id": str(assistant_msg.id)},
                )
        except Exception as e:
            logger.error("问答后台生成失败: conv=%s err=%s", cid, e, exc_info=True)
            # 已生成部分内容也落库，避免完全丢失
            await self._save_partial_on_error(conv_id, full_text, citations, tool_calls)
            await bus.clear_stream_buffer(cid)
            await bus.publish(cid, "error", {"message": f"生成失败：{e}"})
        finally:
            await bus.clear_stream_buffer(cid)
            await bus.release_turn_lock(cid)

    async def _generate_events(
        self,
        user_id: uuid.UUID,
        conv: Conversation,
        body: ChatStreamRequest,
        attachments: list[dict],
        citations: list[dict],
    ) -> AsyncGenerator[dict, None]:
        """问答生成核心：组装 prompt/工具 → 按强弱模型/多模态分流 → 产出统一事件字典。

        事件类型：token / tool_call|tool_start / tool_result / final / citation。
        citations 由调用方传入，工具执行时回写；生成末尾再以 citation 事件吐出。
        """
        user_text = body.message.strip()
        agent = await self.agent_repo.get_by_user(user_id)
        persona = await self.persona_repo.get_active(user_id)
        temperature = persona.temperature if persona else 0.7
        skill = None
        if body.skill_id:
            skill = await self.skill_repo.get(user_id, body.skill_id)
        model, config = await build_default_chat_model(
            self.session, user_id, temperature=temperature, streaming=True
        )
        base_prompt = self._compose_system_prompt(persona, skill)
        stats_holder: dict[str, dict] = {}
        composed_text = _compose_with_attachments(user_text, attachments)

        from app.core.agent.context_hint import current_context_block

        async def _assemble_prompt(has_tools: bool) -> str:
            """组装 system prompt：人设/技能 + 时效引导 + 主动召回 + 跨会话 + 真人模式。"""
            sp = (
                base_prompt + "\n\n" + current_context_block(with_tool_hint=has_tools)
            ).strip()
            if agent is not None and agent.human_mode:
                from app.core.agent.prompt_renderer import render_agent_prompt

                sp = (sp + "\n\n" + render_agent_prompt("human_style.jinja2")).strip()
            if agent is None or agent.enable_active_recall:
                recall = await self._recall_memory(user_id, user_text)
                if recall:
                    sp = (sp + "\n\n" + recall).strip()
            if agent is not None and agent.enable_cross_session:
                cross = await self._cross_session_context(user_id, conv.id)
                if cross:
                    sp = (sp + "\n\n" + cross).strip()
            return sp

        history = await self._history_messages(conv.id)

        if body.image_keys:
            # 多模态输入：用多模态模型看图回答（不走工具编排，无需 MCP 会话）
            system_prompt = await _assemble_prompt(has_tools=False)
            async for token in self._stream_multimodal(
                user_id, system_prompt, history, composed_text, body.image_keys
            ):
                yield {"type": "token", "text": token}
            if citations:
                yield {"type": "citation", "citations": citations}
            return

        # 非多模态：在「持久 MCP 会话」上下文里构建工具并跑编排，
        # 整轮工具调用复用同一批 MCP 会话，不重复握手（退出自动关会话）。
        overrides, kb_ids = await self._tool_scope(user_id, body, skill)
        async with build_enabled_tools_cm(
            self.session, user_id, citations, overrides, stats_holder, kb_ids
        ) as tools:
            system_prompt = await _assemble_prompt(has_tools=bool(tools))
            if not tools:
                # 无工具：纯流式
                lc_messages: list = []
                if system_prompt:
                    lc_messages.append(SystemMessage(content=system_prompt))
                lc_messages.extend(history)
                lc_messages.append(HumanMessage(content=composed_text))
                async for chunk in model.astream(lc_messages):
                    if chunk.content:
                        yield {"type": "token", "text": chunk.content}
            elif supports_function_call(config):
                # 强模型：原生 function calling
                lc_messages = []
                if system_prompt:
                    lc_messages.append(SystemMessage(content=system_prompt))
                lc_messages.extend(history)
                lc_messages.append(HumanMessage(content=composed_text))
                async for ev in run_function_calling(
                    model, tools, lc_messages, stats_holder=stats_holder
                ):
                    yield ev
            else:
                # 弱模型：ReAct
                async for ev in run_react(
                    model, tools, composed_text, history, system_prompt,
                    stats_holder=stats_holder,
                ):
                    yield ev

            if citations:
                yield {"type": "citation", "citations": citations}

    async def _save_partial_on_error(
        self,
        conv_id: uuid.UUID,
        full_text: str,
        citations: list[dict],
        tool_calls: list[dict],
    ) -> None:
        """后台生成异常时，把已生成的部分回复落库，避免完全丢失。失败只记 warning。"""
        text = (full_text or "").strip()
        if not text:
            return
        try:
            async with SessionLocal() as session:
                await MessageRepository(session).add(
                    Message(
                        conversation_id=conv_id,
                        role=ROLE_ASSISTANT,
                        content=text,
                        meta_data={
                            "citations": citations,
                            "tool_calls": tool_calls,
                            "interrupted": True,
                        },
                    )
                )
                await ConversationRepository(session).touch(conv_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("保存部分回复失败: conv=%s err=%s", conv_id, e)

    async def _stream_multimodal(
        self,
        user_id: uuid.UUID,
        system_prompt: str,
        history: list,
        user_text: str,
        image_keys: list[str],
    ):
        """多模态流式：读图转 base64，用多模态模型看图答。逐 token 产出。

        大图先压缩（缩放 + 重编码），避免 base64 过大触发多模态接口 400/超限。
        """
        import base64

        from langchain_core.messages import HumanMessage, SystemMessage

        config = await get_default_config_for_type(
            self.session, user_id, "multimodal", "多模态"
        )
        model = build_chat_model(config, temperature=0.7, streaming=True)

        storage = get_storage()
        content_parts: list[dict] = [{"type": "text", "text": user_text}]
        for key in image_keys[:4]:  # 单轮最多 4 张
            try:
                raw = await storage.get(key)
                from pathlib import Path

                from app.core.rag.image_compress import compress_for_vision

                data, mime = compress_for_vision(raw, Path(key).suffix)
                b64 = base64.b64encode(data).decode()
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                })
            except Exception as e:
                logger.warning("读取/压缩对话图片失败（跳过）: %s", e)

        messages: list = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.extend(history)
        messages.append(HumanMessage(content=content_parts))

        async for chunk in model.astream(messages):
            if chunk.content:
                text = chunk.content if isinstance(chunk.content, str) else str(chunk.content)
                yield text

    async def _dispatch_memory(self, user_id: uuid.UUID, user_text: str) -> None:
        """把本轮用户表达落 memories(source=auto) 并派发萃取任务。失败不影响问答。"""
        try:
            from app.models.memory_model import MEMORY_SOURCE_AUTO, Memory
            from app.tasks.memory import extract_memory_task

            memory = Memory(
                user_id=user_id, raw_text=user_text, source=MEMORY_SOURCE_AUTO
            )
            self.session.add(memory)
            await self.session.commit()
            await self.session.refresh(memory)
            extract_memory_task.delay(str(memory.id))
        except Exception as e:
            logger.warning("对话记忆萃取派发失败（忽略）: %s", e)

    async def _ingest_chat_images(
        self, user_id: uuid.UUID, image_keys: list[str]
    ) -> None:
        """把对话里上传的图片纳入图片库（建 Image 记录 + 派发处理）。

        按 file_key 去重，失败不影响对话。
        """
        try:
            from app.services.image_service import ImageService

            service = ImageService(self.session)
            for key in image_keys:
                try:
                    await service.ingest_from_chat(user_id, key)
                except Exception as e:
                    logger.warning("对话图片入库失败（跳过 %s）: %s", key, e)
        except Exception as e:
            logger.warning("对话图片入库整体失败（忽略）: %s", e)

    def _dispatch_emotion(
        self,
        user_id: uuid.UUID,
        user_text: str,
        conversation_id: uuid.UUID,
        message_id: uuid.UUID,
    ) -> None:
        """派发本轮用户发言的情绪分析任务（异步，仅入队）。失败不影响问答。"""
        text = (user_text or "").strip()
        if not text:
            return
        try:
            from app.tasks.emotion import analyze_emotion_task

            analyze_emotion_task.delay(
                str(user_id), text, str(conversation_id), str(message_id)
            )
        except Exception as e:
            logger.warning("情绪分析派发失败（忽略）: user=%s err=%s", user_id, e)

    # ── 消息反馈 / 重新生成 ──

    async def set_feedback(
        self,
        user_id: uuid.UUID,
        message_id: uuid.UUID,
        rating: str,
        comment: str | None = None,
    ) -> dict:
        """对某条 AI 回复点赞/踩（幂等，可切换）。校验消息归属当前用户。"""
        from app.core.exceptions import BizError
        from app.repositories.message_feedback_repository import (
            MessageFeedbackRepository,
        )

        msg = await self.msg_repo.get(message_id)
        if not msg:
            raise BizError("消息不存在", code=4010, status_code=404)
        conv = await self.conv_repo.get(user_id, msg.conversation_id)
        if not conv:
            raise BizError("无权操作该消息", code=4011, status_code=403)
        fb = await MessageFeedbackRepository(self.session).upsert(
            user_id, message_id, msg.conversation_id, rating, comment
        )
        return {"id": str(fb.id), "rating": fb.rating}

    async def remove_feedback(
        self, user_id: uuid.UUID, message_id: uuid.UUID
    ) -> None:
        """取消对某条 AI 回复的反馈。"""
        from app.repositories.message_feedback_repository import (
            MessageFeedbackRepository,
        )

        await MessageFeedbackRepository(self.session).remove(user_id, message_id)

    async def regenerate(
        self, user_id: uuid.UUID, message_id: uuid.UUID
    ) -> AsyncGenerator[str, None]:
        """重新生成某条 AI 回复：删掉该回复，用它前面的上文重新流式作答。

        约束：只能重新生成 assistant 消息；其前一条 user 消息作为本轮问题。
        """
        from app.core.exceptions import BizError
        from app.models.conversation_model import ROLE_ASSISTANT, ROLE_USER

        target = await self.msg_repo.get(message_id)
        if not target or target.role != ROLE_ASSISTANT:
            yield _sse("error", {"message": "只能重新生成 AI 回复"})
            return
        conv = await self.conv_repo.get(user_id, target.conversation_id)
        if not conv:
            yield _sse("error", {"message": "无权操作该消息"})
            return

        # 找到该 assistant 消息之前最近的一条 user 消息作为问题
        all_msgs = await self.msg_repo.list_by_conversation(conv.id)
        idx = next((i for i, m in enumerate(all_msgs) if m.id == message_id), -1)
        if idx <= 0:
            yield _sse("error", {"message": "找不到对应的提问"})
            return
        user_msg = None
        for i in range(idx - 1, -1, -1):
            if all_msgs[i].role == ROLE_USER:
                user_msg = all_msgs[i]
                break
        if user_msg is None:
            yield _sse("error", {"message": "找不到对应的提问"})
            return

        # 删除旧的 assistant 回复（及其反馈随级联删除），重新走问答
        try:
            await self.msg_repo.delete(target)
        except BizError:
            raise
        except Exception as e:
            yield _sse("error", {"message": f"重新生成失败：{e}"})
            return

        body = ChatStreamRequest(
            conversation_id=conv.id, message=user_msg.content
        )
        # 复用流式问答；但用户消息已存在，这里跳过再次落 user 消息
        async for chunk in self.stream_chat(user_id, body, skip_user_message=True):
            yield chunk


__all__ = ["ChatService"]
