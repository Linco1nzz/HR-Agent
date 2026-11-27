"""确认表单内上传的简历：只保存原始文件与解析文本，不发起评分。

上传文件按 ``{upload_id}`` 命名落在简历上传目录的 ``agent_uploads/`` 下，元数据
写成同名 ``.json`` 旁车文件；确认提交给 ``score_resume`` 后由工具读取并评分，
评分成功后清理临时文件。任务被重启标记失败时残留文件不参与任何查询。
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import aiofiles

from app.core.config import settings
from app.core.exceptions import AgentUploadNotFoundError, ResumeParseError
from app.core.logging import get_logger
from app.schemas.agent import AgentResumeUploadResponse
from app.services import resume_parser_service

logger = get_logger(__name__)

#: 上传子目录（相对 settings.resume_upload_dir）
_SUBDIR = "agent_uploads"


def _upload_directory() -> Path:
    """返回确认表单上传目录，不存在时创建。"""
    root = Path(settings.resume_upload_dir) / _SUBDIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def _file_path(upload_id: str) -> Path:
    """按 upload_id 找到原始文件（扩展名在元数据里）。"""
    metadata = _read_metadata(upload_id)
    return _upload_directory() / f"{upload_id}{metadata['suffix']}"


def _metadata_path(upload_id: str) -> Path:
    return _upload_directory() / f"{upload_id}.json"


def _read_metadata(upload_id: str) -> dict[str, str]:
    """读取上传元数据；不存在时抛 404 业务异常。"""
    path = _metadata_path(upload_id)
    if not path.is_file():
        raise AgentUploadNotFoundError(details={"upload_id": upload_id})
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AgentUploadNotFoundError(details={"upload_id": upload_id}) from exc
    if not isinstance(data, dict) or not isinstance(data.get("filename"), str):
        raise AgentUploadNotFoundError(details={"upload_id": upload_id})
    data.setdefault("suffix", "")
    return {key: str(value) for key, value in data.items()}


async def save_upload(filename: str, content: bytes) -> AgentResumeUploadResponse:
    """校验并保存上传的简历，返回只解析不评分的上传标识。"""
    suffix = resume_parser_service.validate_resume(filename, len(content))
    resume_text = await resume_parser_service.extract_resume_text(content, filename)
    if not resume_text.strip():
        raise ResumeParseError("简历文件无法解析出有效文本")

    upload_id = uuid4().hex
    directory = _upload_directory()
    async with aiofiles.open(directory / f"{upload_id}{suffix}", "wb") as handle:
        await handle.write(content)
    async with aiofiles.open(_metadata_path(upload_id), "w", encoding="utf-8") as handle:
        await handle.write(
            json.dumps(
                {"filename": Path(filename).name, "suffix": suffix},
                ensure_ascii=False,
            )
        )
    logger.info(
        "agent_resume_uploaded",
        upload_id=upload_id,
        filename=Path(filename).name,
        resume_chars=len(resume_text),
    )
    return AgentResumeUploadResponse(
        upload_id=upload_id,
        filename=Path(filename).name,
        resume_chars=len(resume_text),
    )


async def load_upload(upload_id: str) -> tuple[str, bytes]:
    """读取上传的原始文件内容；不存在时抛 404。"""
    metadata = _read_metadata(upload_id)
    path = _file_path(upload_id)
    if not path.is_file():
        raise AgentUploadNotFoundError(details={"upload_id": upload_id})
    async with aiofiles.open(path, "rb") as handle:
        content = await handle.read()
    return metadata["filename"], content


def cleanup_upload(upload_id: str) -> None:
    """评分成功后清理临时文件；清理失败只记日志。"""
    try:
        _file_path(upload_id).unlink(missing_ok=True)
        _metadata_path(upload_id).unlink(missing_ok=True)
    except OSError as exc:  # pragma: no cover - 文件系统异常
        logger.warning("agent_resume_upload_cleanup_failed", upload_id=upload_id, error=str(exc))
