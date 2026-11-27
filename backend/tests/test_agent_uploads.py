"""确认表单内简历上传单元测试：保存、解析、读取与清理（不依赖外部服务）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import settings
from app.core.exceptions import AgentUploadNotFoundError, UnsupportedResumeFormatError
from app.services.agent import uploads

_RESUME_TEXT = "张三\n5 年 Python 开发经验\n熟悉 FastAPI 与 PostgreSQL\n"


@pytest.fixture()
def upload_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把上传目录指向临时目录，避免污染仓库内 uploads/。"""
    monkeypatch.setattr(settings, "resume_upload_dir", str(tmp_path / "resumes"))
    return tmp_path


async def test_save_load_and_cleanup(upload_dir: Path) -> None:
    """上传后能按 upload_id 读回原文，清理后不可再读。"""
    assert upload_dir.exists()
    response = await uploads.save_upload("张三.txt", _RESUME_TEXT.encode("utf-8"))

    assert response.upload_id
    assert response.filename == "张三.txt"
    assert response.resume_chars == len(_RESUME_TEXT.strip())

    filename, content = await uploads.load_upload(response.upload_id)
    assert filename == "张三.txt"
    assert content.decode("utf-8") == _RESUME_TEXT

    uploads.cleanup_upload(response.upload_id)
    with pytest.raises(AgentUploadNotFoundError):
        await uploads.load_upload(response.upload_id)


async def test_unsupported_format_rejected(upload_dir: Path) -> None:
    """不支持的扩展名直接拒绝。"""
    with pytest.raises(UnsupportedResumeFormatError):
        await uploads.save_upload("resume.exe", b"MZ")


async def test_empty_resume_rejected(upload_dir: Path) -> None:
    """解析不出文本时拒绝，避免后续评分空跑。"""
    with pytest.raises(Exception):  # noqa: B017 - ResumeParseError 或文件空错误
        await uploads.save_upload("empty.txt", b"   ")


async def test_unknown_upload_id(upload_dir: Path) -> None:
    """不存在的 upload_id 抛 404 业务异常。"""
    with pytest.raises(AgentUploadNotFoundError):
        await uploads.load_upload("not-exists")
