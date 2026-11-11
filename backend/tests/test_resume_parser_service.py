"""简历文件解析测试：格式 / 大小校验与文本提取。"""

from __future__ import annotations

import io

import pytest
from docx import Document

from app.core.exceptions import ResumeParseError, ResumeTooLargeError, UnsupportedResumeFormatError
from app.services import resume_parser_service


def make_docx_bytes(*paragraphs: str) -> bytes:
    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "技能"
    table.cell(0, 1).text = "Vue 3"
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_validate_resume_accepts_supported_extension() -> None:
    assert resume_parser_service.validate_resume("候选人.PDF", 1024) == ".pdf"
    assert resume_parser_service.validate_resume("resume.docx", 1024) == ".docx"


def test_validate_resume_rejects_unsupported_extension() -> None:
    with pytest.raises(UnsupportedResumeFormatError):
        resume_parser_service.validate_resume("resume.zip", 1024)


def test_validate_resume_rejects_too_large_file() -> None:
    too_large = 10 * 1024 * 1024 + 1

    with pytest.raises(ResumeTooLargeError):
        resume_parser_service.validate_resume("resume.pdf", too_large)


def test_validate_resume_rejects_empty_file() -> None:
    with pytest.raises(ResumeParseError):
        resume_parser_service.validate_resume("resume.pdf", 0)


async def test_extract_txt_supports_gbk() -> None:
    content = "张三\n5 年前端开发经验".encode("gbk")

    text = await resume_parser_service.extract_resume_text(content, "resume.txt")

    assert "张三" in text
    assert "5 年前端开发经验" in text


async def test_extract_docx_includes_paragraphs_and_tables() -> None:
    content = make_docx_bytes("张三", "高级前端工程师")

    text = await resume_parser_service.extract_resume_text(content, "resume.docx")

    assert "张三" in text
    assert "高级前端工程师" in text
    assert "Vue 3" in text


async def test_extract_resume_rejects_empty_text() -> None:
    with pytest.raises(ResumeParseError):
        await resume_parser_service.extract_resume_text(b"   \n  ", "resume.txt")


async def test_extract_resume_rejects_overlong_text() -> None:
    content = ("前端经验" * 30_000).encode()

    with pytest.raises(ResumeParseError):
        await resume_parser_service.extract_resume_text(content, "resume.txt")


def test_extract_doc_falls_back_to_system_converter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(resume_parser_service, "_try_antiword", lambda _path: None)
    monkeypatch.setattr(resume_parser_service, "_try_catdoc", lambda _path: "旧版 DOC 内容")

    assert resume_parser_service._extract_doc(b"fake-doc") == "旧版 DOC 内容"
