"""对话路由：会话 CRUD + SSE 流式问答。"""
import uuid

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.response import success
from app.core.storage import build_file_key, get_storage
from app.db.postgres import get_session
from app.models.user_model import User
from app.schemas.chat_schema import (
    ChatStreamRequest,
    ConversationCreateRequest,
    ConversationRenameRequest,
    FeedbackRequest,
)
from app.services.chat_service import ChatService
from app.services.conversation_service import ConversationService

router = APIRouter(tags=["chat"])


# ── 会话管理 ──

@router.get("/conversations")
async def list_conversations(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = ConversationService(session)
    items = await service.list_conversations(user.id)
    return success([service.to_out_dict(c) for c in items])


@router.post("/conversations")
async def create_conversation(
    body: ConversationCreateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = ConversationService(session)
    conv = await service.create(user.id, body.title)
    return success(service.to_out_dict(conv), "已创建")


@router.put("/conversations/{conv_id}")
async def rename_conversation(
    conv_id: uuid.UUID,
    body: ConversationRenameRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = ConversationService(session)
    conv = await service.rename(user.id, conv_id, body.title)
    return success(service.to_out_dict(conv))


@router.delete("/conversations/{conv_id}")
async def delete_conversation(
    conv_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await ConversationService(session).delete(user.id, conv_id)
    return success(message="删除成功")


@router.get("/conversations/{conv_id}/messages")
async def list_messages(
    conv_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = ConversationService(session)
    return success(await service.list_messages(user.id, conv_id))


# ── 流式问答 ──

@router.post("/chat/stream")
async def chat_stream(
    body: ChatStreamRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = ChatService(session)
    return StreamingResponse(
        service.stream_chat(user.id, body),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat/upload-image")
async def upload_chat_image(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    """对话多模态：上传图片，返回 file_key（随消息一起发）与可访问 url。"""
    import uuid as _uuid
    from pathlib import Path

    content = await file.read()
    ext = Path(file.filename or "img.jpg").suffix.lower() or ".jpg"
    file_key = build_file_key(str(user.id), "chat", str(_uuid.uuid4()), ext)
    storage = get_storage()
    await storage.save(file_key, content)
    return success({"file_key": file_key, "url": storage.get_url(file_key)})


@router.post("/chat/upload-file")
async def upload_chat_file(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    """对话临时附件：上传文档解析成纯文本，仅服务本次对话，不进知识库。

    支持 PDF/Word/Markdown/TXT/HTML；文本超长截断，避免吃满上下文。
    """
    from pathlib import Path

    from app.core.exceptions import BizError
    from app.core.rag.parser import parse_document

    # 对话附件文本上限（约覆盖十几页文档前部），超出截断
    max_chars = 10000

    file_name = file.filename or "文件"
    ext = Path(file_name).suffix.lower()
    allowed = {".pdf", ".docx", ".md", ".markdown", ".txt", ".html", ".htm"}
    if ext not in allowed:
        raise BizError("仅支持 PDF / Word / Markdown / TXT / HTML", code=3001)

    content = await file.read()
    try:
        text = parse_document(ext, content)
    except BizError:
        raise
    except Exception as e:
        raise BizError(f"文档解析失败：{e}", code=3002) from e

    text = (text or "").strip()
    if not text:
        raise BizError("未能从文档中解析出文本内容", code=3003)

    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars]

    return success(
        {
            "file_name": file_name,
            "text": text,
            "chars": len(text),
            "truncated": truncated,
        }
    )


# ── 消息反馈 / 重新生成 ──

@router.post("/chat/messages/{message_id}/feedback")
async def set_message_feedback(
    message_id: uuid.UUID,
    body: FeedbackRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """对某条 AI 回复点赞/踩（幂等，可切换）。"""
    data = await ChatService(session).set_feedback(
        user.id, message_id, body.rating, body.comment
    )
    return success(data, "已反馈")


@router.delete("/chat/messages/{message_id}/feedback")
async def remove_message_feedback(
    message_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """取消对某条 AI 回复的反馈。"""
    await ChatService(session).remove_feedback(user.id, message_id)
    return success(message="已取消反馈")


@router.post("/chat/messages/{message_id}/regenerate")
async def regenerate_message(
    message_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """重新生成某条 AI 回复（SSE 流式，复用问答管线）。"""
    service = ChatService(session)
    return StreamingResponse(
        service.regenerate(user.id, message_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
