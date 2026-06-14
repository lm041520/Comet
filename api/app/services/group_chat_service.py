"""群聊业务服务：多角色卡按主持人调度依次发言（SSE 流式）。

与单聊（ChatService）分离：群聊上下文是多方 transcript、需主持人调度、逐角色冒泡，
逻辑差异大。群聊不做记忆萃取；工具调用由群级开关 enable_tools 控制（默认关，全群统一）。
开启后每个角色发言走单聊的工具编排（function calling / ReAct），能查知识库/记忆/联网/MCP。

SSE 事件：
- meta：{conversation_id, title}
- speaker_start：{persona_id, name, avatar_url} 某角色开始发言
- token：{text} 当前角色的流式 token
- tool_start / tool_result：当前角色调用工具的标记（仅 enable_tools 时）
- speaker_end：{persona_id, message_id} 某角色发言结束（已落库）
- done：{conversation_id}
- error：{message}
"""
import json
import uuid
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent.group_chat import (
    build_speaker_messages,
    build_transcript,
    decide_speakers,
    parse_mention,
    stream_speaker,
)
from app.core.exceptions import BizError
from app.core.llm.chat_model import (
    build_chat_model,
    build_default_chat_model,
    get_default_config_for_type,
    supports_function_call,
)
from app.core.logging import get_logger
from app.core.storage import get_storage
from app.models.conversation_model import (
    ROLE_ASSISTANT,
    ROLE_USER,
    Conversation,
    Message,
)
from app.repositories.agent_persona_repository import AgentPersonaRepository
from app.repositories.conversation_repository import (
    ConversationRepository,
    MessageRepository,
)
from app.schemas.group_chat_schema import GroupChatStreamRequest, GroupCreateRequest

logger = get_logger(__name__)

# 群成员数量约束
MIN_MEMBERS = 2
MAX_MEMBERS = 5
# 群聊历史窗口（取最近多少条消息构 transcript）
HISTORY_LIMIT = 40


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class GroupChatService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.conv_repo = ConversationRepository(session)
        self.msg_repo = MessageRepository(session)
        self.persona_repo = AgentPersonaRepository(session)

    # ── 群会话管理 ──

    async def create_group(
        self, user_id: uuid.UUID, body: GroupCreateRequest
    ) -> Conversation:
        """新建群聊会话：校验成员数量与归属。"""
        ids = list(dict.fromkeys(body.member_persona_ids))  # 去重保序
        if not (MIN_MEMBERS <= len(ids) <= MAX_MEMBERS):
            raise BizError(
                f"群成员需 {MIN_MEMBERS}~{MAX_MEMBERS} 个角色", code=4060
            )
        # 校验每个角色卡都归属当前用户
        members = []
        for pid in ids:
            persona = await self.persona_repo.get(user_id, pid)
            if persona is None:
                raise BizError("选择的角色不存在", code=4061, status_code=404)
            members.append(persona)
        title = (body.title or "").strip() or "、".join(m.name for m in members)[:40]
        title = await self._dedup_title(user_id, title[:256])
        conv = Conversation(
            user_id=user_id,
            title=title[:256],
            is_group=True,
            member_persona_ids=[str(i) for i in ids],
            enable_tools=bool(body.enable_tools),
        )
        created = await self.conv_repo.create(conv)
        logger.info(
            "创建群聊: user=%s conv=%s members=%d", user_id, created.id, len(ids)
        )
        return created

    async def _dedup_title(self, user_id: uuid.UUID, title: str) -> str:
        """群聊标题去重：同基础名已存在时自动追加「（N）」区分。

        基础名指剥掉末尾「（数字）」后的部分，便于「开新对话」复用同组角色时
        生成「原名（2）（3）…」这样递增、可读的标题。
        """
        import re

        from sqlalchemy import select

        from app.models.conversation_model import Conversation as _Conv

        base = re.sub(r"（\d+）$", "", title).strip() or "群聊"
        result = await self.session.execute(
            select(_Conv.title).where(
                _Conv.user_id == user_id, _Conv.is_group.is_(True)
            )
        )
        existing = {(t or "") for (t,) in result.all()}
        if base not in existing and title not in existing:
            return title
        # 找到下一个可用编号
        n = 2
        while f"{base}（{n}）" in existing:
            n += 1
        return f"{base}（{n}）"

    async def get_group_or_404(
        self, user_id: uuid.UUID, conv_id: uuid.UUID
    ) -> Conversation:
        """取群聊会话，不存在或非群聊则报错。"""
        conv = await self.conv_repo.get(user_id, conv_id)
        if conv is None or not conv.is_group:
            raise BizError("群聊会话不存在", code=4062, status_code=404)
        return conv

    async def list_members(
        self, user_id: uuid.UUID, conv_id: uuid.UUID
    ) -> list[dict]:
        """对外：获取群成员（校验会话归属）。"""
        conv = await self.get_group_or_404(user_id, conv_id)
        return await self._load_members(user_id, conv)

    async def _load_members(self, user_id: uuid.UUID, conv: Conversation) -> list[dict]:
        """加载群成员角色卡，返回 [{id, name, system_prompt, avatar_url}]（按存储顺序）。"""
        members: list[dict] = []
        for pid in conv.member_persona_ids or []:
            try:
                persona = await self.persona_repo.get(user_id, uuid.UUID(str(pid)))
            except (ValueError, TypeError):
                persona = None
            if persona is None:
                continue
            avatar_url = None
            if persona.avatar_key:
                try:
                    avatar_url = get_storage().get_url(persona.avatar_key)
                except Exception as e:
                    logger.warning("群成员头像 url 失败: %s", e)
            members.append(
                {
                    "id": str(persona.id),
                    "name": persona.name,
                    "system_prompt": persona.system_prompt or "",
                    "avatar_url": avatar_url,
                }
            )
        return members

    async def _history_for_transcript(self, conv_id: uuid.UUID) -> list[dict]:
        """取群聊历史并附上每条的发言人名字（供 transcript 渲染）。

        群成员发言落库时把角色名存进 meta_data.sender_name，这里直接读取，
        无需回查角色卡（角色卡可能已被改名/删除，以发言时的名字为准）。
        """
        msgs = await self.msg_repo.recent_history(conv_id, HISTORY_LIMIT)
        out: list[dict] = []
        for m in msgs:
            sender_name = None
            if m.role == ROLE_ASSISTANT and m.meta_data:
                sender_name = m.meta_data.get("sender_name")
            out.append(
                {
                    "role": m.role,
                    "content": m.content,
                    "sender_name": sender_name,
                }
            )
        return out

    async def stream_group_chat(
        self, user_id: uuid.UUID, body: GroupChatStreamRequest
    ) -> AsyncGenerator[str, None]:
        user_text = body.message.strip()
        # 取群会话
        conv = await self.conv_repo.get(user_id, body.conversation_id)
        if conv is None or not conv.is_group:
            yield _sse("error", {"message": "群聊会话不存在"})
            return

        yield _sse("meta", {"conversation_id": str(conv.id), "title": conv.title})

        try:
            members = await self._load_members(user_id, conv)
            if len(members) < MIN_MEMBERS:
                yield _sse("error", {"message": "群成员不足，无法对话"})
                return
            member_names = [m["name"] for m in members]
            name_to_member = {m["name"]: m for m in members}

            # 本轮图片（多模态看图）：存进 user 消息 meta_data，供历史还原与分享
            image_keys = list(body.image_keys or [])
            user_meta = {"image_keys": image_keys} if image_keys else None
            # 落库用户消息
            await self.msg_repo.add(
                Message(
                    conversation_id=conv.id,
                    role=ROLE_USER,
                    content=user_text,
                    meta_data=user_meta,
                )
            )

            # 构 transcript（含刚落库的用户消息）
            history = await self._history_for_transcript(conv.id)
            transcript = build_transcript(history)

            # 决定发言顺序：@ 指定优先（跳过主持人），否则主持人调度
            mentioned = parse_mention(user_text, member_names)
            if mentioned:
                speakers = [mentioned]
            else:
                host_model, _ = await build_default_chat_model(
                    self.session, user_id, temperature=0.3, streaming=False
                )
                speakers = await decide_speakers(
                    host_model, members, transcript, user_text
                )
        except BizError as e:
            yield _sse("error", {"message": e.message})
            return
        except Exception as e:
            logger.error("群聊准备失败: %s", e, exc_info=True)
            yield _sse("error", {"message": f"群聊出错：{e}"})
            return

        # 依次让每个角色发言，transcript 一轮内动态累加（接话）
        try:
            speaker_model, self._speaker_config = await build_default_chat_model(
                self.session, user_id, temperature=0.8, streaming=True
            )
        except Exception as e:
            yield _sse("error", {"message": f"模型加载失败：{e}"})
            return

        # 群级工具开关：开启则每个角色发言走工具编排，否则纯人设流式
        tools = []
        if conv.enable_tools:
            try:
                from app.core.agent.tools import build_enabled_tools
                from app.repositories.knowledge_base_repository import (
                    KnowledgeBaseRepository,
                )

                self._tool_citations = []
                self._tool_stats = {}
                kb_ids = await KnowledgeBaseRepository(
                    self.session
                ).list_chat_enabled_ids(user_id)
                tools = await build_enabled_tools(
                    self.session,
                    user_id,
                    self._tool_citations,
                    stats_holder=self._tool_stats,
                    kb_ids=kb_ids,
                )
            except Exception as e:
                logger.warning("群聊工具构建失败（降级为纯对话）: %s", e)
                tools = []

        # 本轮带图：切多模态模型 + 预读图片为内容块（每个角色看同一组图发言）
        image_parts: list[dict] = []
        if image_keys:
            try:
                mm_config = await get_default_config_for_type(
                    self.session, user_id, "multimodal", "多模态"
                )
                speaker_model = build_chat_model(
                    mm_config, temperature=0.8, streaming=True
                )
                self._speaker_config = mm_config
                image_parts = await self._load_image_parts(image_keys)
            except BizError as e:
                yield _sse("error", {"message": e.message})
                return
            except Exception as e:
                logger.warning("群聊多模态准备失败（降级为纯文本）: %s", e)
                image_parts = []

        for name in speakers:
            member = name_to_member.get(name)
            if not member:
                continue
            yield _sse(
                "speaker_start",
                {
                    "persona_id": member["id"],
                    "name": member["name"],
                    "avatar_url": member["avatar_url"],
                },
            )
            full_text = ""
            tool_calls: list[dict] = []
            try:
                async for ev in self._speak(
                    speaker_model,
                    member,
                    member_names,
                    transcript,
                    tools,
                    image_parts,
                ):
                    if ev["type"] == "token":
                        full_text += ev["text"]
                        yield _sse("token", {"text": ev["text"]})
                    elif ev["type"] == "tool_start":
                        tool_calls.append(
                            {"tool": ev["tool"], "query": ev.get("query", "")}
                        )
                        yield _sse(
                            "tool_start",
                            {"tool": ev["tool"], "query": ev.get("query", "")},
                        )
                    elif ev["type"] == "tool_result":
                        yield _sse(
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
                    elif ev["type"] == "final" and not full_text:
                        full_text = ev["text"]
            except Exception as e:
                logger.warning("群成员发言失败（跳过）: %s err=%s", name, e)
                continue

            full_text = full_text.strip()
            if not full_text:
                continue
            # 落库该角色发言（sender_name + 工具调用存进 meta_data 供历史还原）
            meta: dict = {"sender_name": member["name"]}
            if tool_calls:
                meta["tool_calls"] = tool_calls
            msg = await self.msg_repo.add(
                Message(
                    conversation_id=conv.id,
                    role=ROLE_ASSISTANT,
                    content=full_text,
                    sender_persona_id=uuid.UUID(member["id"]),
                    meta_data=meta,
                )
            )
            # 累加进 transcript，使后面的角色能看到这句（接话）
            transcript = transcript + f"\n【{member['name']}】{full_text}"
            yield _sse(
                "speaker_end",
                {"persona_id": member["id"], "message_id": str(msg.id)},
            )

        await self.conv_repo.touch(conv.id)
        yield _sse("done", {"conversation_id": str(conv.id)})

    async def _load_image_parts(self, image_keys: list[str]) -> list[dict]:
        """读图片并压缩成多模态内容块（LangChain image_url 格式）。"""
        import base64
        from pathlib import Path

        from app.core.rag.image_compress import compress_for_vision

        storage = get_storage()
        parts: list[dict] = []
        for key in image_keys[:4]:  # 单轮最多 4 张
            try:
                raw = await storage.get(key)
                data, mime = compress_for_vision(raw, Path(key).suffix)
                b64 = base64.b64encode(data).decode()
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    }
                )
            except Exception as e:
                logger.warning("群聊读取/压缩图片失败（跳过）: %s", e)
        return parts

    async def _speak(
        self,
        model,
        member: dict,
        member_names: list[str],
        transcript: str,
        tools: list,
        image_parts: list[dict] | None = None,
    ) -> AsyncGenerator[dict, None]:
        """让单个角色发言。

        - 无图无工具：纯人设流式。
        - 有工具（且模型支持 function calling）：走编排，可调知识库/记忆/联网/MCP。
        - 有图：发言消息带图片内容块，让角色看图分析；与工具可叠加（多模态模型支持
          function calling 时边看图边调工具，如发股票图各角色联网查实时行情分析）。
        """
        from langchain_core.messages import HumanMessage, SystemMessage

        from app.core.agent.orchestrator import run_function_calling, run_react

        image_parts = image_parts or []
        # 角色发言的 system prompt（人设 + 群聊场景说明 + 当前日期）
        sys_messages = build_speaker_messages(
            member["system_prompt"],
            member["name"],
            member_names,
            transcript,
            with_tool_hint=bool(tools),
        )
        system_prompt = sys_messages[0].content if sys_messages else ""
        turn_text = f"现在轮到你「{member['name']}」发言，请基于上面的群聊记录自然接话。"

        # 纯人设、无图：直接流式
        if not tools and not image_parts:
            async for token in stream_speaker(
                model, member["system_prompt"], member["name"], member_names, transcript
            ):
                yield {"type": "token", "text": token}
            return

        # 构造本轮 user 消息：带图时用多模态内容块（文字 + 图）
        if image_parts:
            human_content: object = [{"type": "text", "text": turn_text}, *image_parts]
        else:
            human_content = turn_text

        can_tool = bool(tools) and supports_function_call(self._speaker_config)

        if tools and not can_tool:
            # 模型不支持 function calling：ReAct 不便带图，带图时退化为看图直答
            if image_parts:
                messages = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=human_content),
                ]
                async for chunk in model.astream(messages):
                    if chunk.content:
                        text = (
                            chunk.content
                            if isinstance(chunk.content, str)
                            else str(chunk.content)
                        )
                        yield {"type": "token", "text": text}
                return
            async for ev in run_react(
                model, tools, turn_text, [], system_prompt,
                stats_holder=self._tool_stats,
            ):
                yield ev
            return

        if can_tool:
            # 看图 + 调工具（function calling 循环；图随首条 user 消息传入）
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=human_content),
            ]
            async for ev in run_function_calling(
                model, tools, messages, stats_holder=self._tool_stats
            ):
                yield ev
            return

        # 仅看图、无工具：多模态直答
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_content),
        ]
        async for chunk in model.astream(messages):
            if chunk.content:
                text = (
                    chunk.content
                    if isinstance(chunk.content, str)
                    else str(chunk.content)
                )
                yield {"type": "token", "text": text}


__all__ = ["GroupChatService"]
