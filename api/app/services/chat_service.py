"""问答业务服务：SSE 流式对话（方案B 工具编排）。

流程：加载默认对话模型 + Agent 配置 → 构建工具（知识库/记忆/联网，按开关）
→ 强模型走原生 function calling / 弱模型走 ReAct → 流式产出 token/工具标记/引用
→ 落库 user/assistant 消息（assistant 带引用与工具调用元信息）
→ 回答后异步派发记忆萃取（对话自动萃取）。
"""
import json
import uuid
from collections.abc import AsyncGenerator

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent.orchestrator import run_function_calling, run_react
from app.core.agent.tools import build_enabled_tools
from app.core.llm.chat_model import (
    build_chat_model,
    build_default_chat_model,
    get_default_config_for_type,
    supports_function_call,
)
from app.core.logging import get_logger
from app.core.storage import get_storage
from app.models.agent_config_model import AgentConfig
from app.models.conversation_model import (
    ROLE_ASSISTANT,
    ROLE_USER,
    Conversation,
    Message,
)
from app.repositories.agent_config_repository import AgentConfigRepository
from app.repositories.conversation_repository import (
    ConversationRepository,
    MessageRepository,
)
from app.schemas.chat_schema import ChatStreamRequest

logger = get_logger(__name__)

MAX_HISTORY_TURNS = 20


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

    async def _build_tools(
        self,
        user_id: uuid.UUID,
        agent: AgentConfig | None,
        body: ChatStreamRequest,
        citations: list[dict],
    ) -> list:
        """按 agent 默认开关 + 本轮覆盖，构建启用的工具列表。

        三个核心工具（知识库/记忆/联网）沿用 agent 配置默认 + 本轮 body 覆盖；
        其余内置工具（时间等）及 MCP 工具由用户 tool_configs 持久启停决定。
        """

        def enabled(override: bool | None, default: bool) -> bool:
            return default if override is None else override

        a_know = agent.enable_knowledge if agent else True
        a_mem = agent.enable_memory if agent else True
        a_web = agent.enable_web_search if agent else False

        # 核心三工具的最终启停作为本轮 overrides，保证与既有行为一致
        overrides = {
            "knowledge_search": enabled(body.enable_knowledge, a_know),
            "memory_search": enabled(body.enable_memory, a_mem),
            "web_search": enabled(body.enable_web_search, a_web),
        }
        return await build_enabled_tools(self.session, user_id, citations, overrides)

    async def stream_chat(
        self, user_id: uuid.UUID, body: ChatStreamRequest, skip_user_message: bool = False
    ) -> AsyncGenerator[str, None]:
        user_text = body.message.strip()
        try:
            conv = await self._ensure_conversation(user_id, body)
        except Exception as e:
            yield _sse("error", {"message": str(e)})
            return

        yield _sse("meta", {"conversation_id": str(conv.id), "title": conv.title})
        # 本轮附件（对话临时文档，不入知识库），存进 user 消息便于后续追问还原
        attachments = [
            {"file_name": a.file_name, "text": a.text} for a in body.attachments if a.text
        ]
        if not skip_user_message:
            await self.msg_repo.add(
                Message(
                    conversation_id=conv.id,
                    role=ROLE_USER,
                    content=user_text,
                    meta_data={"attachments": attachments} if attachments else None,
                )
            )

        try:
            agent = await self.agent_repo.get_by_user(user_id)
            temperature = agent.temperature if agent else 0.7
            model, config = await build_default_chat_model(
                self.session, user_id, temperature=temperature, streaming=True
            )
            system_prompt = (agent.system_prompt.strip() if agent else "") or ""
            citations: list[dict] = []
            tools = await self._build_tools(user_id, agent, body, citations)
            history = await self._history_messages(conv.id)
        except Exception as e:
            yield _sse("error", {"message": str(e)})
            return

        full_text = ""
        tool_calls: list[dict] = []
        # 当前问题（含本轮附件全文）；多模态分支用纯问题
        composed_text = _compose_with_attachments(user_text, attachments)
        try:
            if body.image_keys:
                # 多模态输入：用多模态模型看图回答（不走工具编排）
                async for token in self._stream_multimodal(
                    user_id, system_prompt, history, composed_text, body.image_keys
                ):
                    full_text += token
                    yield _sse("token", {"text": token})
            elif not tools:
                # 无工具：纯流式
                lc_messages: list = []
                if system_prompt:
                    lc_messages.append(SystemMessage(content=system_prompt))
                lc_messages.extend(history)
                lc_messages.append(HumanMessage(content=composed_text))
                async for chunk in model.astream(lc_messages):
                    if chunk.content:
                        full_text += chunk.content
                        yield _sse("token", {"text": chunk.content})
            elif supports_function_call(config):
                # 强模型：原生 function calling
                lc_messages = []
                if system_prompt:
                    lc_messages.append(SystemMessage(content=system_prompt))
                lc_messages.extend(history)
                lc_messages.append(HumanMessage(content=composed_text))
                async for ev in run_function_calling(model, tools, lc_messages):
                    full_text, tool_calls = await self._emit(
                        ev, full_text, tool_calls
                    )
                    out = self._event_to_sse(ev)
                    if out:
                        yield out
            else:
                # 弱模型：ReAct
                async for ev in run_react(model, tools, composed_text, history, system_prompt):
                    full_text, tool_calls = await self._emit(
                        ev, full_text, tool_calls
                    )
                    out = self._event_to_sse(ev)
                    if out:
                        yield out
        except Exception as e:
            logger.error("问答生成失败: %s", e, exc_info=True)
            yield _sse("error", {"message": f"生成失败：{e}"})
            return

        # 引用事件
        if citations:
            yield _sse("citation", {"citations": citations})

        # 存 assistant 消息（带引用 + 工具调用元信息）
        assistant_msg = await self.msg_repo.add(
            Message(
                conversation_id=conv.id,
                role=ROLE_ASSISTANT,
                content=full_text,
                meta_data={"citations": citations, "tool_calls": tool_calls},
            )
        )
        await self.conv_repo.touch(conv.id)

        # 回答后异步萃取记忆（对话自动萃取，不阻塞用户：仅落库+派发，萃取在 worker）
        await self._dispatch_memory(user_id, user_text)

        # 回答后异步分析用户情绪（重新生成时跳过，避免对同一句话重复分析）
        if not skip_user_message:
            self._dispatch_emotion(user_id, user_text, conv.id, assistant_msg.id)

        yield _sse(
            "done",
            {"conversation_id": str(conv.id), "message_id": str(assistant_msg.id)},
        )

    @staticmethod
    async def _emit(
        ev: dict, full_text: str, tool_calls: list[dict]
    ) -> tuple[str, list[dict]]:
        """累积文本与工具调用记录。"""
        if ev["type"] == "token":
            full_text += ev["text"]
        elif ev["type"] == "tool_call":
            tool_calls.append({"tool": ev["tool"], "query": ev.get("query", "")})
        elif ev["type"] == "final" and not full_text:
            full_text = ev["text"]
        return full_text, tool_calls

    @staticmethod
    def _event_to_sse(ev: dict) -> str | None:
        """编排事件 → SSE。final 不单独发（token 已累积）。"""
        if ev["type"] == "token":
            return _sse("token", {"text": ev["text"]})
        if ev["type"] == "tool_call":
            return _sse("tool_call", {"tool": ev["tool"], "query": ev.get("query", "")})
        return None

    async def _stream_multimodal(
        self,
        user_id: uuid.UUID,
        system_prompt: str,
        history: list,
        user_text: str,
        image_keys: list[str],
    ):
        """多模态流式：读图转 base64，用多模态模型看图答。逐 token 产出。"""
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
                b64 = base64.b64encode(raw).decode()
                mime = "image/png" if key.lower().endswith(".png") else "image/jpeg"
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                })
            except Exception as e:
                logger.warning("读取对话图片失败（跳过）: %s", e)

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
