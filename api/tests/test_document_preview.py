"""文档原文件预览行为测试。"""

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.services.document_service import DocumentService


def _document(file_ext: str):
    return SimpleNamespace(
        id=uuid.uuid4(),
        file_name=f"preview{file_ext}",
        file_ext=file_ext,
        file_key=f"user/documents/preview{file_ext}",
        source_url=None,
    )


def test_pdf_preview_returns_proxy_and_signed_download_without_parsing() -> None:
    doc = _document(".pdf")
    service = DocumentService(Mock())
    service._get_or_404 = AsyncMock(return_value=doc)
    storage = Mock()
    storage.get_url.return_value = "https://example.oss/preview.pdf?signed=1"
    storage.get = AsyncMock(side_effect=AssertionError("PDF 预览不应读取原文件"))

    with patch("app.services.document_service.get_storage", return_value=storage):
        result = asyncio.run(service.preview(uuid.uuid4(), doc.id))

    assert result["preview_type"] == "pdf"
    assert result["preview_url"] == f"/api/documents/{doc.id}/preview-file"
    assert result["download_url"] == "https://example.oss/preview.pdf?signed=1"
    assert result["expires_in"] == 600
    assert result["content"] == ""
    storage.get_url.assert_called_once_with(doc.file_key, expires=600)
    storage.get.assert_not_awaited()


def test_text_preview_keeps_existing_content_path() -> None:
    doc = _document(".txt")
    service = DocumentService(Mock())
    service._get_or_404 = AsyncMock(return_value=doc)
    storage = Mock()
    storage.get = AsyncMock(return_value="预览正文".encode())

    with patch("app.services.document_service.get_storage", return_value=storage):
        result = asyncio.run(service.preview(uuid.uuid4(), doc.id))

    assert result["preview_type"] == "text"
    assert result["preview_url"] is None
    assert result["download_url"] is None
    assert result["content"] == "预览正文"
    storage.get.assert_awaited_once_with(doc.file_key)


def test_pdf_preview_file_reads_original_bytes_without_parsing() -> None:
    doc = _document(".pdf")
    service = DocumentService(Mock())
    service._get_or_404 = AsyncMock(return_value=doc)
    storage = Mock()
    storage.get = AsyncMock(return_value=b"%PDF-test")

    with patch("app.services.document_service.get_storage", return_value=storage):
        returned_doc, content = asyncio.run(
            service.get_preview_file(uuid.uuid4(), doc.id)
        )

    assert returned_doc is doc
    assert content == b"%PDF-test"
    storage.get.assert_awaited_once_with(doc.file_key)
