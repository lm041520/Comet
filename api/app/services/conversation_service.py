"""会话管理业务服务：会话 CRUD + 历史消息。"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError
from app.models.conversation_model import Conversation
from app.repositories.conversation_repository import (
    ConversationRepository,
    MessageRepository,
)


class ConversationService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ConversationRepository(session)
        self.msg_repo = MessageRepository(session)

    async def create(self, user_id: uuid.UUID, title: str = "新对话") -> Conversation:
        return await self.repo.create(Conversation(user_id=user_id, title=title))

    async def get_owned(
        self, user_id: uuid.UUID, conv_id: uuid.UUID
    ) -> Conversation:
        conv = await self.repo.get(user_id, conv_id)
        if not conv:
            raise BizError("会话不存在", code=4002, status_code=404)
        return conv

    async def list_conversations(self, user_id: uuid.UUID) -> list[Conversation]:
        return await self.repo.list_by_user(user_id)

    async def rename(
        self, user_id: uuid.UUID, conv_id: uuid.UUID, title: str
    ) -> Conversation:
        conv = await self.get_owned(user_id, conv_id)
        conv.title = title
        return await self.repo.save(conv)

    async def delete(self, user_id: uuid.UUID, conv_id: uuid.UUID) -> None:
        conv = await self.get_owned(user_id, conv_id)
        await self.repo.delete(conv)

    async def list_messages(
        self, user_id: uuid.UUID, conv_id: uuid.UUID
    ) -> list[dict]:
        await self.get_owned(user_id, conv_id)
        messages = await self.msg_repo.list_by_conversation(conv_id)
        # 带上当前用户对各消息的反馈（赞/踩），供前端高亮
        from app.repositories.message_feedback_repository import (
            MessageFeedbackRepository,
        )

        feedbacks = await MessageFeedbackRepository(self.session).list_by_conversation(
            user_id, conv_id
        )
        rating_by_msg = {str(f.message_id): f.rating for f in feedbacks}
        return [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "meta_data": m.meta_data,
                "sender_persona_id": str(m.sender_persona_id)
                if m.sender_persona_id
                else None,
                "sender_name": (m.meta_data or {}).get("sender_name")
                if m.meta_data
                else None,
                "feedback": rating_by_msg.get(str(m.id)),
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ]

    @staticmethod
    def to_out_dict(conv: Conversation) -> dict:
        return {
            "id": str(conv.id),
            "title": conv.title,
            "is_group": conv.is_group,
            "member_persona_ids": conv.member_persona_ids or [],
            "enable_tools": conv.enable_tools,
            "created_at": conv.created_at.isoformat() if conv.created_at else None,
            "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
        }
