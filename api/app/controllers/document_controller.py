"""知识库文档路由：上传/网页导入/列表/详情/状态/重试/删除/检索。"""
import uuid

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.response import success
from app.db.postgres import get_session
from app.models.user_model import User
from app.schemas.document_schema import (
    RetrievalValidationRequest,
    SearchRequest,
    UrlImportRequest,
)
from app.schemas.knowledge_base_schema import MoveToKbRequest
from app.services.document_service import DocumentService

router = APIRouter(prefix="/documents", tags=["document"])


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    kb_id: uuid.UUID | None = Form(default=None),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    content = await file.read()
    service = DocumentService(session)
    doc = await service.upload(user.id, file.filename or "未命名", content, kb_id)
    return success(await service.to_out_dict(doc), "上传成功，正在解析")


@router.post("/from-url")
async def import_from_url(
    body: UrlImportRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = DocumentService(session)
    doc = await service.import_url(user.id, body.url, body.kb_id)
    return success(await service.to_out_dict(doc), "导入成功，正在解析")


@router.get("")
async def list_documents(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    tag: str | None = Query(default=None, description="按标签名筛选"),
    kb_id: uuid.UUID | None = Query(default=None, description="按知识库筛选"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = DocumentService(session)
    docs, total = await service.list_documents(user.id, page, page_size, tag, kb_id)
    items = [await service.to_out_dict(d) for d in docs]
    return success(
        {"total": total, "page": page, "page_size": page_size, "items": items}
    )


@router.get("/{doc_id}")
async def get_document(
    doc_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = DocumentService(session)
    doc = await service.get_detail(user.id, doc_id)
    return success(await service.to_out_dict(doc))


@router.get("/{doc_id}/preview")
async def preview_document(
    doc_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """获取原文件预览；PDF 返回鉴权预览地址，文本格式返回正文。"""
    data = await DocumentService(session).preview(user.id, doc_id)
    return success(data)


@router.get("/{doc_id}/preview-file")
async def preview_document_file(
    doc_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """返回 PDF 原始字节，由浏览器内置 PDF Viewer 显示。"""
    _doc, content = await DocumentService(session).get_preview_file(user.id, doc_id)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline"},
    )


@router.get("/{doc_id}/status")
async def get_status(
    doc_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = DocumentService(session)
    doc = await service.get_detail(user.id, doc_id)
    return success(
        {"status": doc.status, "progress": doc.progress, "error_msg": doc.error_msg}
    )


@router.post("/{doc_id}/retry")
async def retry_document(
    doc_id: uuid.UUID,
    parser: str = Query(default="auto", description="auto/plain/pymupdf/docling"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = DocumentService(session)
    doc = await service.retry(user.id, doc_id, parser)
    return success(await service.to_out_dict(doc), "已重新提交解析")


@router.delete("/{doc_id}")
async def delete_document(
    doc_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await DocumentService(session).delete(user.id, doc_id)
    return success(message="删除成功")


@router.post("/search")
async def search_documents(
    body: SearchRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    hits = await DocumentService(session).search(
        user.id, body.query, body.top_k, body.tags, body.kb_id
    )
    return success(hits)


@router.post("/retrieval-validation")
async def validate_retrieval(
    body: RetrievalValidationRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    data = await DocumentService(session).validate_retrieval(
        user.id,
        body.kb_id,
        body.query,
        body.top_k,
    )
    return success(data)


@router.put("/{doc_id}/move")
async def move_document(
    doc_id: uuid.UUID,
    body: MoveToKbRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    service = DocumentService(session)
    doc = await service.move_to_kb(user.id, doc_id, uuid.UUID(body.kb_id))
    return success(await service.to_out_dict(doc), "已移动")
