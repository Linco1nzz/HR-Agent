"""知识库文档解析：格式 / 大小校验与文本提取。

上传的文件先落盘保存，再由本模块复制到临时文件后解析（避免解析器锁定或改写
原文件）；PDF / DOCX 复用项目已有依赖（pdfplumber / python-docx），文本类文件
按常见编码解码，旧版 DOC 依次尝试 antiword / catdoc / LibreOffice。解析后统一
做换行与空白归一化。
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import (
    DocumentFileTooLargeError,
    DocumentParseError,
    UnsupportedDocumentFormatError,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

SUPPORTED_DOCUMENT_EXTENSIONS = (".pdf", ".docx", ".doc", ".txt", ".md", ".markdown", ".csv")
SUPPORTED_DOCUMENT_LABEL = "PDF、DOC、DOCX、TXT、MD、CSV"

#: 解析后的文本上限，避免超大文件占满内存与数据库
MAX_DOCUMENT_TEXT_LENGTH = 2_000_000
_TEMP_PREFIX = "hr_kb_"
_DOC_TIMEOUT_SECONDS = 60
_TEXT_ENCODINGS = ("utf-8-sig", "utf-16", "gbk", "gb18030", "big5", "latin-1")
_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".csv": "text/csv",
}


def guess_mime_type(filename: str) -> str:
    """按扩展名推断 MIME 类型，未知扩展名回退到二进制流。"""
    suffix = Path(filename).suffix.lower()
    return _MIME_TYPES.get(suffix, "application/octet-stream")


def validate_document(filename: str | None, file_size: int) -> str:
    """校验文档文件名与大小，返回小写扩展名（如 ``.pdf``）。"""
    safe_name = Path(filename or "").name
    suffix = Path(safe_name).suffix.lower()
    if not safe_name or suffix not in SUPPORTED_DOCUMENT_EXTENSIONS:
        raise UnsupportedDocumentFormatError(
            f"仅支持 {SUPPORTED_DOCUMENT_LABEL} 格式的文档",
            details={
                "filename": safe_name or None,
                "supported_extensions": list(SUPPORTED_DOCUMENT_EXTENSIONS),
            },
        )

    max_bytes = settings.knowledge_base_max_file_size_mb * 1024 * 1024
    if file_size <= 0:
        raise DocumentParseError("文档内容为空")
    if file_size > max_bytes:
        raise DocumentFileTooLargeError(
            f"文档不能超过 {settings.knowledge_base_max_file_size_mb}MB",
            details={
                "max_size_mb": settings.knowledge_base_max_file_size_mb,
                "file_size": file_size,
            },
        )
    return suffix


async def extract_document_text(content: bytes, filename: str) -> str:
    """把文件内容写入临时文件后解析出纯文本。

    :raises DocumentParseError: 解析失败或没有提取到有效文本。
    """
    suffix = validate_document(filename, len(content))
    try:
        text = await asyncio.to_thread(_extract_from_temp_file, content, suffix)
    except DocumentParseError:
        raise
    except Exception as exc:
        logger.warning("document_parse_failed", filename=filename, file_type=suffix, error=str(exc))
        raise DocumentParseError(f"无法解析该 {suffix.lstrip('.').upper()} 文件") from exc

    text = _normalize_text(text)
    if not text:
        raise DocumentParseError("无法从文档中提取有效文本，请确认文件不是扫描件或空文档")
    if len(text) > MAX_DOCUMENT_TEXT_LENGTH:
        raise DocumentParseError(f"文档文本超过 {MAX_DOCUMENT_TEXT_LENGTH} 字符，请拆分后重新上传")
    return text


# ---------------------------------------------------------------------------
# 同步解析实现（由 asyncio.to_thread 调用，避免阻塞事件循环）
# ---------------------------------------------------------------------------
def _extract_from_temp_file(content: bytes, suffix: str) -> str:
    """核心约束：解析始终基于临时文件，不直接操作已保存的原文件。"""
    with tempfile.TemporaryDirectory(prefix=_TEMP_PREFIX) as tmp:
        path = Path(tmp) / f"source{suffix}"
        path.write_bytes(content)

        if suffix in {".txt", ".md", ".markdown", ".csv"}:
            return _load_text_file(path)
        if suffix == ".pdf":
            return _extract_pdf(path)
        if suffix == ".docx":
            return _extract_docx(path)
        return _extract_legacy_doc(path, Path(tmp))


def _load_text_file(path: Path) -> str:
    """文本类文件按常见编码依次尝试解码（UTF-8 优先，兼容 GBK / Big5）。"""
    return _decode_bytes(path.read_bytes())


def _extract_pdf(path: Path) -> str:
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    return "\n".join(pages)


def _extract_docx(path: Path) -> str:
    from docx import Document as DocxDocument

    document = DocxDocument(str(path))
    parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    parts.append(cell.text)
    return "\n".join(parts)


def _extract_legacy_doc(path: Path, output_dir: Path) -> str:
    """旧版 DOC：依次尝试系统转换工具。"""
    for command in _doc_commands(path):
        text = _run_text_command(command)
        if text and text.strip():
            return text

    converted = _convert_with_soffice(path, output_dir)
    if converted:
        return converted

    raise DocumentParseError(
        "无法解析旧版 DOC 文件，请安装 antiword / LibreOffice，或将文件另存为 DOCX 后重试"
    )


def _doc_commands(path: Path) -> list[list[str]]:
    commands: list[list[str]] = []
    antiword = shutil.which("antiword")
    if antiword:
        commands.append([antiword, "-m", "UTF-8", str(path)])
    catdoc = shutil.which("catdoc")
    if catdoc:
        commands.append([catdoc, "-w", str(path)])
    return commands


def _run_text_command(command: list[str]) -> str | None:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=_DOC_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("document_doc_command_failed", command=command[0], error=str(exc))
        return None

    if result.returncode != 0:
        return None
    text = _decode_bytes(result.stdout)
    return text if text.strip() else None


def _convert_with_soffice(path: Path, output_dir: Path) -> str | None:
    executable = shutil.which("soffice") or shutil.which("libreoffice")
    if not executable:
        return None

    try:
        subprocess.run(
            [
                executable,
                "--headless",
                "--convert-to",
                "txt:Text",
                "--outdir",
                str(output_dir),
                str(path),
            ],
            capture_output=True,
            timeout=_DOC_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("document_soffice_failed", error=str(exc))
        return None

    converted = output_dir / f"{path.stem}.txt"
    if converted.exists():
        return _decode_bytes(converted.read_bytes())
    return None


# ---------------------------------------------------------------------------
# 文本辅助
# ---------------------------------------------------------------------------
def _decode_bytes(content: bytes) -> str:
    for encoding in _TEXT_ENCODINGS:
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="ignore")


def _normalize_text(text: str) -> str:
    text = text.replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    normalized = "\n".join(lines)
    while "\n\n\n" in normalized:
        normalized = normalized.replace("\n\n\n", "\n\n")
    return normalized.strip()
