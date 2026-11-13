"""文档解析服务测试：格式 / 大小校验与临时文件文本提取。"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.core.exceptions import (
    DocumentFileTooLargeError,
    DocumentParseError,
    UnsupportedDocumentFormatError,
)
from app.services import document_parser_service


async def test_extract_text_from_txt() -> None:
    text = await document_parser_service.extract_document_text(
        "第一段内容\n\n第二段内容".encode(),
        "制度.txt",
    )

    assert text == "第一段内容\n\n第二段内容"


async def test_extract_text_falls_back_to_gbk() -> None:
    text = await document_parser_service.extract_document_text(
        "员工手册：年假规定".encode("gbk"),
        "handbook.md",
    )

    assert "年假规定" in text


async def test_extract_text_normalizes_whitespace() -> None:
    text = await document_parser_service.extract_document_text(
        "第一行   \r\n\r\n\r\n第二行\t".encode(),
        "note.txt",
    )

    assert text == "第一行\n\n第二行"


async def test_extract_text_rejects_empty_content() -> None:
    with pytest.raises(DocumentParseError):
        await document_parser_service.extract_document_text(b"   \n\n", "empty.txt")


def test_validate_document_rejects_unsupported_extension() -> None:
    with pytest.raises(UnsupportedDocumentFormatError):
        document_parser_service.validate_document("virus.exe", 10)


def test_validate_document_rejects_oversized_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "knowledge_base_max_file_size_mb", 1)

    with pytest.raises(DocumentFileTooLargeError):
        document_parser_service.validate_document("big.txt", 2 * 1024 * 1024)


def test_guess_mime_type() -> None:
    assert document_parser_service.guess_mime_type("a.PDF") == "application/pdf"
    assert document_parser_service.guess_mime_type("a.md") == "text/markdown"
    assert document_parser_service.guess_mime_type("a.unknown") == "application/octet-stream"
