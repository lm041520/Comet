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
from contextlib import AsyncExitStack

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
from app.core.realtime import bus
from app.core.storage import get_storage
from app.db.postgres import SessionLocal
from app.models.conversation_model import (
    ROLE_ASSISTANT,
    ROLE_USER,
    Conversation,
    Message,
)
from app.models.group_member_model import (
    GROUP_ROLE_MEMBER,
    GROUP_ROLE_OWNER,
    GroupMember,
)
from app.repositories.agent_persona_repository import AgentPersonaRepository
from app.repositories.conversation_repository import (
    ConversationRepository,
    MessageRepository,
)
from app.repositories.group_member_repository import GroupMemberRepository
from app.schemas.group_chat_schema import (
    GroupChatStreamRequest,
    GroupCreateRequest,
    GroupSayRequest,
)

logger = get_logger(__name__)

# 群成员数量约束
MIN_MEMBERS = 2
MAX_MEMBERS = 5
# 群聊历史窗口（取最近多少条消息构 transcript；越短首字越快、越省 token）
HISTORY_LIMIT = 24

# 后台 AI 回合任务引用集合（防止 create_task 的任务被 GC 提前回收）
_BG_TASKS: set = set()


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class GroupChatService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.conv_repo = ConversationRepository(session)
        self.msg_repo = MessageRepository(session)
        self.persona_repo = AgentPersonaRepository(session)
        self.member_repo = GroupMemberRepository(session)

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
        """对外：获取群成员角色卡（群主或已加入成员均可；角色卡归属群主）。"""
        conv = await self.get_group_for_member(user_id, conv_id)
        return await self._load_members(conv.user_id, conv)

    async def _human_mode(self, user_id: uuid.UUID) -> bool:
        """读用户全局真人模式开关（群主级，应用到全群角色）。失败默认关。"""
        try:
            from app.repositories.agent_config_repository import AgentConfigRepository

            cfg = await AgentConfigRepository(self.session).get_by_user(user_id)
            return bool(cfg.human_mode) if cfg else False
        except Exception as e:  # noqa: BLE001
            logger.warning("读取真人模式开关失败（默认关）: %s", e)
            return False

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

    async def avatar_members(self, conv: Conversation) -> list[dict]:
        """群头像宫格用的成员列表：真人成员（群主+加入者）+ AI 角色卡，最多取 4 个。

        真人在前（群主优先）、AI 在后，仿微信群头像把真实参与者也拼进去。
        真人头像走鉴权接口 /api/groups/{id}/members/{uid}/avatar；AI 走 /api/files。
        """
        from app.models.user_model import User

        out: list[dict] = []
        # 真人成员（群主排第一）
        try:
            humans = await self.member_repo.list_by_conversation(conv.id)
            humans_sorted = sorted(humans, key=lambda m: 0 if m.role == "owner" else 1)
            for m in humans_sorted:
                u = await self.session.get(User, m.user_id)
                has_avatar = bool(u and u.avatar)
                name = (m.nickname or "").strip() or await self._default_nickname(
                    m.user_id
                )
                out.append({
                    "name": name,
                    "avatar_url": (
                        f"/api/groups/{conv.id}/members/{m.user_id}/avatar"
                        if has_avatar
                        else None
                    ),
                })
        except Exception as e:
            logger.warning("群头像真人成员加载失败（忽略）: %s", e)
        # AI 角色卡
        for pid in conv.member_persona_ids or []:
            try:
                persona = await self.persona_repo.get(
                    conv.user_id, uuid.UUID(str(pid))
                )
            except (ValueError, TypeError):
                persona = None
            if persona is None:
                continue
            avatar_url = None
            if persona.avatar_key:
                try:
                    avatar_url = get_storage().get_url(persona.avatar_key)
                except Exception as e:
                    logger.warning("群头像角色卡头像 url 失败: %s", e)
            out.append({"name": persona.name, "avatar_url": avatar_url})
        return out[:4]

    async def _history_for_transcript(self, conv_id: uuid.UUID) -> list[dict]:
        """取群聊历史并附上每条的发言人名字（供 transcript 渲染）。

        - AI 角色发言：名字存在 meta_data.sender_name（发言时的角色名）。
        - 真人发言：多人群聊里 meta_data.sender_name 存发言真人的昵称；单人群聊
          的 user 消息无 sender_name，transcript 渲染时回退为「用户」。
        """
        msgs = await self.msg_repo.recent_history(conv_id, HISTORY_LIMIT)
        out: list[dict] = []
        for m in msgs:
            sender_name = m.meta_data.get("sender_name") if m.meta_data else None
            out.append(
                {
                    "role": m.role,
                    "content": m.content,
                    "sender_name": sender_name,
                }
            )
        return out

    # ── 多人实时群聊：成员 / 邀请 / 加入 ──

    @staticmethod
    def _gen_join_code() -> str:
        """生成 8 位邀请码（去掉易混字符 0/O/1/I/L）。"""
        import secrets

        alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
        return "".join(secrets.choice(alphabet) for _ in range(8))

    async def _default_nickname(self, user_id: uuid.UUID) -> str:
        """群内显示昵称：优先用户昵称 → 用户名 → 邮箱前缀 → 兜底「用户」。"""
        from app.models.user_model import User

        u = await self.session.get(User, user_id)
        if u:
            if u.nickname and u.nickname.strip():
                return u.nickname.strip()[:64]
            if u.username and u.username.strip():
                return u.username.split("@")[0].strip()[:64]
            if u.email:
                return u.email.split("@")[0][:64]
        return "用户"

    async def _get_conv_any(self, conv_id: uuid.UUID) -> Conversation | None:
        """不限归属地按 id 取会话（成员鉴权前的原始查询）。"""
        from sqlalchemy import select

        result = await self.session.execute(
            select(Conversation).where(Conversation.id == conv_id)
        )
        return result.scalar_one_or_none()

    async def _ensure_owner_member(self, conv: Conversation) -> None:
        """确保群主在 group_members 里有一条 owner 记录（兼容历史群聊）。"""
        existing = await self.member_repo.get(conv.id, conv.user_id)
        if existing is None:
            nickname = await self._default_nickname(conv.user_id)
            await self.member_repo.add(
                GroupMember(
                    conversation_id=conv.id,
                    user_id=conv.user_id,
                    role=GROUP_ROLE_OWNER,
                    nickname=nickname,
                )
            )

    async def get_group_for_member(
        self, user_id: uuid.UUID, conv_id: uuid.UUID
    ) -> Conversation:
        """取群聊会话并校验当前用户是群成员（群主或已加入者）。"""
        conv = await self._get_conv_any(conv_id)
        if conv is None or not conv.is_group:
            raise BizError("群聊会话不存在", code=4062, status_code=404)
        if conv.user_id == user_id:
            return conv
        member = await self.member_repo.get(conv_id, user_id)
        if member is None:
            raise BizError("你不是该群成员", code=4063, status_code=403)
        return conv

    async def get_or_create_join_code(
        self, user_id: uuid.UUID, conv_id: uuid.UUID
    ) -> str:
        """群主获取邀请码（无则生成）。"""
        conv = await self.get_group_or_404(user_id, conv_id)  # 仅群主
        await self._ensure_owner_member(conv)
        if not conv.join_code:
            conv.join_code = self._gen_join_code()
            await self.conv_repo.save(conv)
        return conv.join_code

    async def set_tools(
        self, user_id: uuid.UUID, conv_id: uuid.UUID, enabled: bool
    ) -> bool:
        """群主开/关本群的工具（知识库/记忆/联网/MCP）。返回最新状态。

        仅群主可改（AI 用群主算力、工具走群主配置）；get_group_or_404 已限定为本人会话。
        """
        conv = await self.get_group_or_404(user_id, conv_id)
        conv.enable_tools = bool(enabled)
        await self.conv_repo.save(conv)
        logger.info(
            "群聊工具开关: conv=%s enabled=%s by=%s", conv_id, enabled, user_id
        )
        return conv.enable_tools

    async def reset_join_code(self, user_id: uuid.UUID, conv_id: uuid.UUID) -> str:
        """群主重置邀请码（旧码失效）。"""
        conv = await self.get_group_or_404(user_id, conv_id)  # 仅群主
        conv.join_code = self._gen_join_code()
        await self.conv_repo.save(conv)
        return conv.join_code

    async def join_by_code(
        self, user_id: uuid.UUID, code: str, nickname: str | None = None
    ) -> Conversation:
        """凭邀请码加入群聊。已是成员则幂等返回。"""
        from sqlalchemy import select

        code = (code or "").strip().upper()
        result = await self.session.execute(
            select(Conversation).where(
                Conversation.join_code == code, Conversation.is_group.is_(True)
            )
        )
        conv = result.scalar_one_or_none()
        if conv is None:
            raise BizError("邀请码无效或已失效", code=4064, status_code=404)
        if conv.user_id == user_id:
            await self._ensure_owner_member(conv)
            return conv
        existing = await self.member_repo.get(conv.id, user_id)
        if existing is None:
            nick = (nickname or "").strip() or await self._default_nickname(user_id)
            await self.member_repo.add(
                GroupMember(
                    conversation_id=conv.id,
                    user_id=user_id,
                    role=GROUP_ROLE_MEMBER,
                    nickname=nick[:64],
                )
            )
            logger.info("加入群聊: user=%s conv=%s", user_id, conv.id)
            await bus.publish(
                str(conv.id), "presence", {"type": "join", "nickname": nick[:64]}
            )
        return conv

    async def leave_group(self, user_id: uuid.UUID, conv_id: uuid.UUID) -> None:
        """退出群聊（群主不可退，只能删群）。"""
        conv = await self.get_group_for_member(user_id, conv_id)
        if conv.user_id == user_id:
            raise BizError("群主不能退群，可直接删除群聊", code=4065)
        member = await self.member_repo.get(conv_id, user_id)
        nick = (member.nickname if member else None) or "成员"
        await self.member_repo.remove(conv_id, user_id)
        await bus.publish(str(conv_id), "presence", {"type": "leave", "nickname": nick})

    async def list_humans(
        self, user_id: uuid.UUID, conv_id: uuid.UUID
    ) -> list[dict]:
        """群里的真人成员列表（含当前用户标记 + 头像地址）。"""
        await self.get_group_for_member(user_id, conv_id)
        conv = await self._get_conv_any(conv_id)
        if conv:
            await self._ensure_owner_member(conv)
        members = await self.member_repo.list_by_conversation(conv_id)
        # 批量取成员的头像 key（判断是否有头像）
        from app.models.user_model import User

        online = await bus.list_online(str(conv_id))
        out: list[dict] = []
        for m in members:
            u = await self.session.get(User, m.user_id)
            has_avatar = bool(u and u.avatar)
            custom = m.nickname
            nickname = (
                custom
                if custom and custom.strip() and custom.strip() != "用户"
                else await self._default_nickname(m.user_id)
            )
            out.append(
                {
                    "user_id": str(m.user_id),
                    "nickname": nickname,
                    "role": m.role,
                    "is_me": m.user_id == user_id,
                    "online": str(m.user_id) in online,
                    "avatar_url": (
                        f"/api/groups/{conv_id}/members/{m.user_id}/avatar"
                        if has_avatar
                        else None
                    ),
                }
            )
        return out

    async def get_member_avatar(
        self,
        user_id: uuid.UUID,
        conv_id: uuid.UUID,
        member_user_id: uuid.UUID,
    ) -> tuple[bytes, str]:
        """读取群内某成员的头像字节（校验请求者也是群成员后服务端直读）。

        绕开 /files 接口「key 必须以本人 id 开头」的限制——群成员之间可看彼此头像，
        但仅限同群、仅头像、服务端读取，不暴露任意文件。
        """
        await self.get_group_for_member(user_id, conv_id)
        # 目标必须确实是该群成员
        target = await self.member_repo.get(conv_id, member_user_id)
        conv = await self._get_conv_any(conv_id)
        is_target_owner = bool(conv and conv.user_id == member_user_id)
        if target is None and not is_target_owner:
            raise BizError("成员不存在", code=4066, status_code=404)
        from app.models.user_model import User

        u = await self.session.get(User, member_user_id)
        if u is None or not u.avatar:
            raise BizError("该成员没有头像", code=4067, status_code=404)
        try:
            content = await get_storage().get(u.avatar)
        except Exception as e:
            logger.warning("读取成员头像失败: %s", e)
            raise BizError("头像读取失败", code=4068, status_code=404) from e
        ext = ("." + u.avatar.rsplit(".", 1)[-1].lower()) if "." in u.avatar else ""
        mime = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }.get(ext, "image/jpeg")
        return content, mime

    async def list_my_groups(self, user_id: uuid.UUID) -> list[Conversation]:
        """我的群聊：自建的 + 凭码加入的（按最近活跃排序）。"""
        from sqlalchemy import or_, select

        joined_subq = (
            select(GroupMember.conversation_id)
            .where(GroupMember.user_id == user_id)
            .scalar_subquery()
        )
        result = await self.session.execute(
            select(Conversation)
            .where(
                Conversation.is_group.is_(True),
                or_(
                    Conversation.user_id == user_id,
                    Conversation.id.in_(joined_subq),
                ),
            )
            .order_by(Conversation.updated_at.desc())
        )
        return list(result.scalars().all())

    async def list_group_messages(
        self, user_id: uuid.UUID, conv_id: uuid.UUID
    ) -> list[dict]:
        """群聊历史消息（成员可读，区分真人发送者与 AI 角色）。"""
        await self.get_group_for_member(user_id, conv_id)
        messages = await self.msg_repo.list_by_conversation(conv_id)
        storage = get_storage()

        def _image_urls(meta: dict | None) -> list[str]:
            keys = (meta or {}).get("image_keys") or []
            urls: list[str] = []
            for k in keys:
                try:
                    urls.append(storage.get_url(k))
                except Exception:
                    continue
            return urls

        out: list[dict] = []
        for m in messages:
            meta = m.meta_data or {}
            sender_user_id = str(m.sender_user_id) if m.sender_user_id else None
            out.append(
                {
                    "id": str(m.id),
                    "role": m.role,
                    "content": m.content,
                    "meta_data": meta,
                    "images": _image_urls(meta),
                    "sender_persona_id": str(m.sender_persona_id)
                    if m.sender_persona_id
                    else None,
                    "sender_user_id": sender_user_id,
                    "sender_name": meta.get("sender_name"),
                    "is_me": sender_user_id == str(user_id),
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
            )
        return out

    # ── 多人实时群聊：发言（广播 + 后台 AI）+ 事件订阅 ──

    async def say(
        self, user_id: uuid.UUID, conv_id: uuid.UUID, body: GroupSayRequest
    ) -> dict:
        """某真人成员发言：落库 → 广播给全员 → 后台触发 AI 接话，立即返回。"""
        conv = await self.get_group_for_member(user_id, conv_id)
        await self._ensure_owner_member(conv)
        member = await self.member_repo.get(conv_id, user_id)
        # 显示名优先用成员自定义昵称（且非占位「用户」），否则按用户实时解析
        custom = member.nickname if member else None
        nickname = (
            custom
            if custom and custom.strip() and custom.strip() != "用户"
            else await self._default_nickname(user_id)
        )
        text = body.message.strip()
        image_keys = list(body.image_keys or [])

        user_meta: dict = {"sender_name": nickname, "sender_user_id": str(user_id)}
        if image_keys:
            user_meta["image_keys"] = image_keys
        msg = await self.msg_repo.add(
            Message(
                conversation_id=conv_id,
                role=ROLE_USER,
                content=text,
                sender_user_id=user_id,
                meta_data=user_meta,
            )
        )
        await self.conv_repo.touch(conv_id)

        # 广播真人发言给全员（含自己，前端统一从 SSE 接收渲染）
        await bus.publish(
            str(conv_id),
            "human_message",
            {
                "message_id": str(msg.id),
                "user_id": str(user_id),
                "nickname": nickname,
                "content": text,
                "image_keys": image_keys,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            },
        )

        # 后台触发 AI 接话（独立 session，不阻塞本次 HTTP）
        import asyncio

        task = asyncio.create_task(
            self._run_ai_turn_bg(conv_id, conv.user_id, text, image_keys)
        )
        _BG_TASKS.add(task)
        task.add_done_callback(_BG_TASKS.discard)
        return {"message_id": str(msg.id)}

    async def _run_ai_turn_bg(
        self,
        conv_id: uuid.UUID,
        owner_id: uuid.UUID,
        user_text: str,
        image_keys: list[str],
    ) -> None:
        """后台任务：用独立 session 跑 AI 角色接话，逐 token 广播到频道。

        用 Redis 回合锁防多人同时发言时重复触发；锁未拿到说明已有回合在生成，
        本次只让真人消息广播、不再触发 AI（避免角色重复刷屏）。
        """
        if not await bus.acquire_turn_lock(str(conv_id)):
            return
        service: GroupChatService | None = None
        try:
            async with SessionLocal() as session:
                service = GroupChatService(session)
                await service._ai_turn(conv_id, owner_id, user_text, image_keys)
        except Exception as e:
            logger.error("群聊后台 AI 回合失败: conv=%s err=%s", conv_id, e, exc_info=True)
            await bus.publish(str(conv_id), "error", {"message": f"AI 接话出错：{e}"})
        finally:
            # 关闭本轮持久 MCP 会话（与开启在同一任务，安全）；失败只记日志
            stack = getattr(service, "_mcp_stack", None) if service else None
            if stack is not None:
                try:
                    await stack.aclose()
                except Exception as e:  # noqa: BLE001
                    logger.warning("关闭群聊 MCP 会话出错（忽略）: %s", e)
            await bus.release_turn_lock(str(conv_id))

    async def _ai_turn(
        self,
        conv_id: uuid.UUID,
        owner_id: uuid.UUID,
        user_text: str,
        image_keys: list[str],
    ) -> None:
        """AI 角色接话一回合：调度发言顺序 → 逐角色流式 → 广播事件并落库。"""
        conv = await self._get_conv_any(conv_id)
        if conv is None or not conv.is_group:
            return
        members = await self._load_members(owner_id, conv)
        if len(members) < MIN_MEMBERS:
            return
        member_names = [m["name"] for m in members]
        name_to_member = {m["name"]: m for m in members}
        cid = str(conv_id)
        human_mode = await self._human_mode(owner_id)

        history = await self._history_for_transcript(conv_id)
        transcript = build_transcript(history)

        # @ 指定优先（跳过主持人），否则主持人调度
        mentioned = parse_mention(user_text, member_names)
        if mentioned:
            speakers = [mentioned]
        else:
            # 广播「AI 正在想怎么接话」占位，消除调度期间的空窗
            await bus.publish(cid, "thinking", {})
            host_model, _ = await build_default_chat_model(
                self.session, owner_id, temperature=0.3, streaming=False
            )
            speakers = await decide_speakers(
                host_model, members, transcript, user_text
            )

        # 主持人判定本轮纯属真人之间聊天 → AI 不接话，直接收尾
        if not speakers:
            await bus.publish(cid, "done", {"conversation_id": cid})
            return

        speaker_model, self._speaker_config = await build_default_chat_model(
            self.session, owner_id, temperature=0.8, streaming=True
        )

        # 群级工具开关：开启则用「持久 MCP 会话」构建工具，整轮多角色复用同一批会话，
        # 不重复握手；会话在 _run_ai_turn_bg 的 finally 里随 self._mcp_stack 关闭，避免泄漏。
        self._mcp_stack = AsyncExitStack()
        tools = []
        if conv.enable_tools:
            try:
                from app.core.agent.tools import build_enabled_tools_cm
                from app.repositories.knowledge_base_repository import (
                    KnowledgeBaseRepository,
                )

                self._tool_citations = []
                self._tool_stats = {}
                kb_ids = await KnowledgeBaseRepository(
                    self.session
                ).list_chat_enabled_ids(owner_id)
                tools = await self._mcp_stack.enter_async_context(
                    build_enabled_tools_cm(
                        self.session,
                        owner_id,
                        self._tool_citations,
                        stats_holder=self._tool_stats,
                        kb_ids=kb_ids,
                    )
                )
            except Exception as e:
                logger.warning("群聊工具构建失败（降级为纯对话）: %s", e)
                tools = []

        # 带图：切多模态模型 + 预读图片
        image_parts: list[dict] = []
        if image_keys:
            try:
                mm_config = await get_default_config_for_type(
                    self.session, owner_id, "multimodal", "多模态"
                )
                speaker_model = build_chat_model(
                    mm_config, temperature=0.8, streaming=True
                )
                self._speaker_config = mm_config
                image_parts = await self._load_image_parts(image_keys)
            except Exception as e:
                logger.warning("群聊多模态准备失败（降级为纯文本）: %s", e)
                image_parts = []

        for name in speakers:
            member = name_to_member.get(name)
            if not member:
                continue
            await bus.publish(
                cid,
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
                    human_mode=human_mode,
                ):
                    if ev["type"] == "token":
                        full_text += ev["text"]
                        await bus.publish(
                            cid,
                            "token",
                            {"persona_id": member["id"], "text": ev["text"]},
                        )
                    elif ev["type"] == "tool_start":
                        tool_calls.append(
                            {"tool": ev["tool"], "query": ev.get("query", "")}
                        )
                        await bus.publish(
                            cid,
                            "tool_start",
                            {"tool": ev["tool"], "query": ev.get("query", "")},
                        )
                    elif ev["type"] == "tool_result":
                        await bus.publish(
                            cid,
                            "tool_result",
                            {
                                "tool": ev["tool"],
                                "query": ev.get("query", ""),
                                "status": ev.get("status", "success"),
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
            meta: dict = {"sender_name": member["name"]}
            if tool_calls:
                meta["tool_calls"] = tool_calls
            msg = await self.msg_repo.add(
                Message(
                    conversation_id=conv_id,
                    role=ROLE_ASSISTANT,
                    content=full_text,
                    sender_persona_id=uuid.UUID(member["id"]),
                    meta_data=meta,
                )
            )
            transcript = transcript + f"\n【{member['name']}】{full_text}"
            await bus.publish(
                cid,
                "speaker_end",
                {"persona_id": member["id"], "message_id": str(msg.id)},
            )

        await self.conv_repo.touch(conv_id)
        await bus.publish(cid, "done", {"conversation_id": cid})

    async def events(
        self, user_id: uuid.UUID, conv_id: uuid.UUID
    ) -> AsyncGenerator[str, None]:
        """SSE：订阅群聊频道，把全员发言与 AI 接话事件实时推给前端。

        附带在线状态维护：建立连接即标记在线、每次心跳刷新、断开时标记离线，
        并广播 presence 事件让其他成员实时更新「谁在线」。
        """
        try:
            await self.get_group_for_member(user_id, conv_id)
        except BizError as e:
            yield _sse("error", {"message": e.message})
            return
        # 成员校验后释放 DB 连接：SSE 长连接期间只用 Redis 订阅，不占用连接池
        try:
            await self.session.close()
        except Exception as e:
            logger.warning("释放群聊订阅 session 失败: %s", e)

        cid = str(conv_id)
        uid = str(user_id)
        await bus.mark_online(cid, uid)
        await bus.publish(cid, "presence", {"type": "online", "user_id": uid})
        # 建立连接先吐一个 ready，前端据此判定订阅成功
        yield _sse("ready", {"conversation_id": cid})
        try:
            async for evt in bus.subscribe(cid):
                event = evt.get("event") or "message"
                if event == "_ping":
                    # 心跳：刷新在线状态 + SSE 注释保活（不触发前端事件）
                    await bus.mark_online(cid, uid)
                    yield ": ping\n\n"
                    continue
                data = evt.get("data") or {}
                yield _sse(event, data)
        finally:
            await bus.mark_offline(cid, uid)
            await bus.publish(cid, "presence", {"type": "offline", "user_id": uid})

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
            human_mode = await self._human_mode(user_id)

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
                    human_mode=human_mode,
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
        human_mode: bool = False,
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
        # 角色发言的 system prompt（人设 + 群聊场景说明 + 当前日期 + 可选真人模式）
        sys_messages = build_speaker_messages(
            member["system_prompt"],
            member["name"],
            member_names,
            transcript,
            with_tool_hint=bool(tools),
            human_mode=human_mode,
        )
        system_prompt = sys_messages[0].content if sys_messages else ""
        turn_text = f"现在轮到你「{member['name']}」发言，请基于上面的群聊记录自然接话。"

        # 纯人设、无图：直接流式
        if not tools and not image_parts:
            async for token in stream_speaker(
                model, member["system_prompt"], member["name"], member_names, transcript,
                human_mode=human_mode,
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
