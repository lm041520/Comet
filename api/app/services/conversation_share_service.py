"""对话分享业务服务：创建（快照冻结）/ 列表 / 取消 / 公开查看。

快照式：创建时把当时会话消息脱敏冻结进 snapshot，原对话后续变化不影响分享。
同会话复用：已有有效分享则刷新其快照并返回，不重复建链接。
"""
import base64
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError
from app.core.logging import get_logger
from app.core.storage import get_storage
from app.models.conversation_model import ROLE_ASSISTANT, ROLE_USER
from app.models.conversation_share_model import ConversationShare
from app.repositories.agent_persona_repository import AgentPersonaRepository
from app.repositories.conversation_repository import (
    ConversationRepository,
    MessageRepository,
)
from app.repositories.conversation_share_repository import (
    ConversationShareRepository,
)

logger = get_logger(__name__)


class ConversationShareService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ConversationShareRepository(session)
        self.conv_repo = ConversationRepository(session)
        self.msg_repo = MessageRepository(session)
        self.persona_repo = AgentPersonaRepository(session)

    async def _avatar_data_url(self, file_key: str | None) -> str | None:
        """把头像 file_key 读出 → 压缩到小尺寸 → base64 data URL（公开页无需鉴权直接显示）。

        头像统一缩到 96px 方形 + JPEG 重编码，体积极小，无需大小门控；
        压缩失败或读取失败返回 None，前端回退默认头像。
        """
        if not file_key:
            return None
        try:
            storage = get_storage()
            if not await storage.exists(file_key):
                return None
            content = await storage.get(file_key)
            if not content:
                return None
            data, mime = self._compress_avatar(content)
            b64 = base64.b64encode(data).decode()
            return f"data:{mime};base64,{b64}"
        except Exception as e:
            logger.warning("头像转 data URL 失败（忽略）: key=%s err=%s", file_key, e)
            return None

    @staticmethod
    def _compress_avatar(raw: bytes) -> tuple[bytes, str]:
        """把头像压成小尺寸方图（中心裁剪到 96px + JPEG）。失败回退原图。"""
        try:
            import io

            from PIL import Image

            img = Image.open(io.BytesIO(raw))
            # 透明通道贴白底转 RGB
            if img.mode in ("RGBA", "P", "LA"):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                img = img.convert("RGBA")
                bg.paste(img, mask=img.split()[-1])
                img = bg
            else:
                img = img.convert("RGB")
            # 中心裁剪成正方形
            w, h = img.size
            side = min(w, h)
            left = (w - side) // 2
            top = (h - side) // 2
            img = img.crop((left, top, left + side, top + side))
            # 缩到 96px（头像展示 34px，2~3 倍足够清晰）
            img = img.resize((96, 96))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=82, optimize=True)
            return buf.getvalue(), "image/jpeg"
        except Exception as e:
            logger.warning("头像压缩失败，用原图: %s", e)
            return raw, "image/png"

    async def _build_snapshot(self, conv_id: uuid.UUID) -> list[dict]:
        """把会话消息脱敏冻结成快照：保留 user/assistant 的文本。

        群聊消息额外带发言人名字 sender_name + 发言人头像 data URL sender_avatar，
        供公开页按发言人区分展示（微信群效果）。
        """
        msgs = await self.msg_repo.list_by_conversation(conv_id)
        snapshot: list[dict] = []
        avatar_cache: dict[str, str | None] = {}  # persona_id -> data URL
        for m in msgs:
            if m.role not in (ROLE_USER, ROLE_ASSISTANT):
                continue
            content = (m.content or "").strip()
            if not content:
                continue
            item: dict = {"role": m.role, "content": content}
            # 群聊发言人信息（单聊消息无 sender_persona_id，不受影响）
            if m.role == ROLE_ASSISTANT and m.sender_persona_id:
                sender_name = (m.meta_data or {}).get("sender_name") if m.meta_data else None
                item["sender_name"] = sender_name
                key = str(m.sender_persona_id)
                if key not in avatar_cache:
                    avatar_cache[key] = await self._persona_avatar_data_url(
                        m.sender_persona_id
                    )
                item["sender_avatar"] = avatar_cache[key]
            snapshot.append(item)
        return snapshot

    async def _persona_avatar_data_url(self, persona_id: uuid.UUID) -> str | None:
        """按角色卡 id 取头像 data URL（群聊快照用）。失败返回 None。"""
        try:
            from app.models.agent_persona_model import AgentPersona

            persona = await self.session.get(AgentPersona, persona_id)
            if persona and persona.avatar_key:
                return await self._avatar_data_url(persona.avatar_key)
        except Exception as e:
            logger.warning("群成员头像 data URL 失败（忽略）: %s", e)
        return None

    async def create_share(
        self,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        expire_days: int | None,
        title: str | None = None,
    ) -> ConversationShare:
        """创建/刷新分享。同会话已有有效分享则刷新快照复用，否则新建。"""
        conv = await self.conv_repo.get(user_id, conversation_id)
        if not conv:
            raise BizError("会话不存在", code=4070, status_code=404)
        snapshot = await self._build_snapshot(conversation_id)
        if not snapshot:
            raise BizError("会话还没有内容，无法分享", code=4071)
        # 分享标题：用户自定义优先，否则用会话标题
        share_title = (title or "").strip() or (conv.title or "对话分享")

        expire_at = None
        if expire_days and expire_days > 0:
            expire_at = datetime.now(timezone.utc) + timedelta(days=expire_days)

        # 解析头像（转 data URL，公开页直接用）：用户头像 + 当前生效角色头像
        user_avatar = None
        ai_avatar = None
        ai_name = None
        try:
            from app.models.user_model import User

            user = await self.session.get(User, user_id)
            if user and getattr(user, "avatar", None):
                user_avatar = await self._avatar_data_url(user.avatar)
            persona = await self.persona_repo.get_active(user_id)
            if persona:
                ai_name = persona.name
                if persona.avatar_key:
                    ai_avatar = await self._avatar_data_url(persona.avatar_key)
        except Exception as e:
            logger.warning("分享头像解析失败（忽略）: %s", e)

        existing = await self.repo.get_active_by_conversation(
            user_id, conversation_id
        )
        if existing:
            # 复用：刷新快照、标题、过期时间、头像
            existing.snapshot = snapshot
            existing.title = share_title
            existing.expire_at = expire_at
            existing.user_avatar = user_avatar
            existing.ai_avatar = ai_avatar
            existing.ai_name = ai_name
            saved = await self.repo.save(existing)
            logger.info("刷新对话分享: user=%s share=%s", user_id, saved.id)
            return saved

        share = ConversationShare(
            user_id=user_id,
            conversation_id=conversation_id,
            share_token=secrets.token_urlsafe(16),
            title=share_title,
            snapshot=snapshot,
            is_active=True,
            expire_at=expire_at,
            user_avatar=user_avatar,
            ai_avatar=ai_avatar,
            ai_name=ai_name,
        )
        created = await self.repo.add(share)
        logger.info("创建对话分享: user=%s share=%s", user_id, created.id)
        return created

    async def list_shares(self, user_id: uuid.UUID) -> list[ConversationShare]:
        return await self.repo.list_by_user(user_id)

    async def revoke(self, user_id: uuid.UUID, share_id: uuid.UUID) -> None:
        """取消分享：置 is_active=false（保留痕迹）。"""
        share = await self.repo.get(user_id, share_id)
        if not share:
            raise BizError("分享不存在", code=4072, status_code=404)
        share.is_active = False
        await self.repo.save(share)
        logger.info("取消对话分享: user=%s share=%s", user_id, share_id)

    async def get_public(self, token: str) -> dict:
        """公开查看（无需登录）：校验有效性 + 浏览数 +1，返回脱敏快照。"""
        share = await self.repo.get_by_token(token)
        if not share or not share.is_active:
            raise BizError("分享不存在或已取消", code=4073, status_code=404)
        if share.expire_at is not None:
            now = datetime.now(timezone.utc)
            exp = share.expire_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < now:
                raise BizError("分享链接已过期", code=4074, status_code=404)
        # 浏览数 +1（失败不影响查看）
        try:
            share.view_count = (share.view_count or 0) + 1
            await self.repo.save(share)
        except Exception as e:
            logger.warning("分享浏览数自增失败（忽略）: %s", e)
        return {
            "title": share.title,
            "messages": share.snapshot or [],
            "user_avatar": share.user_avatar,
            "ai_avatar": share.ai_avatar,
            "ai_name": share.ai_name,
            "created_at": share.created_at.isoformat() if share.created_at else None,
        }

    def share_out(self, share: ConversationShare) -> dict:
        return {
            "id": str(share.id),
            "conversation_id": str(share.conversation_id),
            "share_token": share.share_token,
            "title": share.title,
            "is_active": share.is_active,
            "expire_at": share.expire_at.isoformat() if share.expire_at else None,
            "view_count": share.view_count or 0,
            "created_at": share.created_at.isoformat() if share.created_at else None,
        }
