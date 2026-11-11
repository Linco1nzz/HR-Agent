"""简历文件解析：格式 / 大小校验与文本提取。

支持 PDF、DOC、DOCX、TXT。PDF 与 DOCX 使用项目已有依赖（pdfplumber /
python-docx）；旧版 DOC 依赖系统工具，依次尝试 antiword、catdoc、LibreOffice，
Windows 上再尝试 Word COM，全部不可用时返回可操作的错误提示。
"""

from __future__ import annotations

import asyncio
import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import (
    ResumeParseError,
    ResumeTooLargeError,
    UnsupportedResumeFormatError,
)
from app.core.logging import get_logger
from app.schemas.resume_evaluation import SUPPORTED_RESUME_EXTENSIONS

logger = get_logger(__name__)

SUPPORTED_FORMATS_LABEL = "PDF、DOC、DOCX、TXT"
#: Dify 开始节点 jianli 的最大长度
MAX_RESUME_TEXT_LENGTH = 80_000
_TEXT_ENCODINGS = ("utf-8-sig", "utf-16", "gbk", "gb18030", "big5", "latin-1")
_DOC_TIMEOUT_SECONDS = 60


def validate_resume(filename: str | None, file_size: int) -> str:
    """校验简历文件名与大小，返回小写扩展名（如 ``.pdf``）。"""
    safe_name = Path(filename or "").name
    suffix = Path(safe_name).suffix.lower()
    if not safe_name or suffix not in SUPPORTED_RESUME_EXTENSIONS:
        raise UnsupportedResumeFormatError(
            f"仅支持 {SUPPORTED_FORMATS_LABEL} 格式的简历",
            details={
                "filename": safe_name or None,
                "supported_extensions": list(SUPPORTED_RESUME_EXTENSIONS),
            },
        )

    max_bytes = settings.resume_max_file_size_mb * 1024 * 1024
    if file_size <= 0:
        raise ResumeParseError("简历文件为空")
    if file_size > max_bytes:
        raise ResumeTooLargeError(
            f"简历文件不能超过 {settings.resume_max_file_size_mb}MB",
            details={"max_size_mb": settings.resume_max_file_size_mb, "file_size": file_size},
        )
    return suffix


async def extract_resume_text(content: bytes, filename: str) -> str:
    """从简历文件中提取纯文本；解析失败抛 :class:`ResumeParseError`。"""
    suffix = validate_resume(filename, len(content))
    try:
        text = await asyncio.to_thread(_extract_text_sync, content, suffix)
    except ResumeParseError:
        raise
    except Exception as exc:
        logger.warning("resume_parse_failed", filename=filename, file_type=suffix, error=str(exc))
        raise ResumeParseError(f"无法解析该 {suffix.lstrip('.').upper()} 文件") from exc

    text = _normalize_text(text)
    if not text:
        raise ResumeParseError("无法从简历中提取有效文本，请确认文件不是扫描件或空文档")
    if len(text) > MAX_RESUME_TEXT_LENGTH:
        raise ResumeParseError(f"简历文本超过 {MAX_RESUME_TEXT_LENGTH} 字符，请精简后重试")
    return text


# ---------------------------------------------------------------------------
# 同步解析实现（由 asyncio.to_thread 调用，避免阻塞事件循环）
# ---------------------------------------------------------------------------
def _extract_text_sync(content: bytes, suffix: str) -> str:
    if suffix == ".pdf":
        return _extract_pdf(content)
    if suffix == ".docx":
        return _extract_docx(content)
    if suffix == ".doc":
        return _extract_doc(content)
    return _decode_bytes(content)


def _extract_pdf(content: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    return "\n".join(pages)


def _extract_docx(content: bytes) -> str:
    from docx import Document

    document = Document(io.BytesIO(content))
    parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    parts.append(cell.text)
    return "\n".join(parts)


def _extract_doc(content: bytes) -> str:
    """旧版 DOC：写入临时文件后依次尝试系统转换工具。"""
    with tempfile.TemporaryDirectory(prefix="hr_resume_") as tmp:
        doc_path = Path(tmp) / "resume.doc"
        doc_path.write_bytes(content)

        text = _try_antiword(doc_path) or _try_catdoc(doc_path) or _try_soffice(doc_path, Path(tmp))
        if text:
            return text

        if os.name == "nt":
            text = _try_word_com(doc_path, Path(tmp))
            if text:
                return text

    raise ResumeParseError(
        "无法解析旧版 DOC 文件，请安装 antiword / LibreOffice，或将文件另存为 DOCX 后重试"
    )


def _try_antiword(path: Path) -> str | None:
    executable = shutil.which("antiword")
    if not executable:
        return None
    return _run_text_command([executable, "-m", "UTF-8", str(path)])


def _try_catdoc(path: Path) -> str | None:
    executable = shutil.which("catdoc")
    if not executable:
        return None
    return _run_text_command([executable, "-w", str(path)])


def _try_soffice(path: Path, output_dir: Path) -> str | None:
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
        logger.warning("resume_soffice_failed", error=str(exc))
        return None

    converted = output_dir / f"{path.stem}.txt"
    if converted.exists():
        return _decode_bytes(converted.read_bytes())
    return None


def _try_word_com(path: Path, output_dir: Path) -> str | None:
    """Windows 上借助已安装的 Word 导出文本（无需 Python COM 依赖）。"""
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        return None

    output_path = output_dir / "resume_word.txt"
    script = f"""
$ErrorActionPreference = 'Stop'
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {{
  $doc = $word.Documents.Open('{_ps_quote(str(path))}', $false, $true)
  $text = $doc.Content.Text
  $doc.Close($false)
  [System.IO.File]::WriteAllText(
    '{_ps_quote(str(output_path))}',
    $text,
    (New-Object System.Text.UTF8Encoding($false))
  )
}} finally {{
  $word.Quit()
}}
"""
    try:
        result = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            timeout=_DOC_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("resume_word_com_failed", error=str(exc))
        return None

    if result.returncode != 0:
        logger.warning(
            "resume_word_com_rejected",
            stderr=result.stderr.decode("utf-8", errors="ignore")[:500],
        )
        return None
    if output_path.exists():
        return _decode_bytes(output_path.read_bytes())
    return None


def _run_text_command(command: list[str]) -> str | None:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=_DOC_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("resume_doc_command_failed", command=command[0], error=str(exc))
        return None

    if result.returncode != 0:
        return None
    text = _decode_bytes(result.stdout)
    return text if text.strip() else None


def _ps_quote(value: str) -> str:
    """PowerShell 单引号字符串转义。"""
    return value.replace("'", "''")


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
