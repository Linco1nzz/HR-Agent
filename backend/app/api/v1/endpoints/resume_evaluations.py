"""简历筛选接口：上传评分、列表、详情与人工复核状态更新。

接口层只做鉴权、参数校验与响应组装；文件解析、Dify 调用与落库位于
:mod:`app.services.resume_evaluation_service`。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DifyClient
from app.core.config import settings
from app.core.exceptions import ResumeTooLargeError
from app.db.session import get_db
from app.schemas.error import ErrorResponse
from app.schemas.resume_evaluation import (
    ResumeEvaluationListResponse,
    ResumeEvaluationRead,
    ResumeEvaluationStatusUpdate,
    ResumeStatus,
)
from app.services import resume_evaluation_service

router = APIRouter(prefix="/resume-evaluations", tags=["resume-evaluations"])

_AUTH_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "缺少令牌、令牌无效或已过期"},
}

_RESUME_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    **_AUTH_ERROR_RESPONSES,
    404: {"model": ErrorResponse, "description": "简历或 JD 不存在"},
    413: {"model": ErrorResponse, "description": "简历文件超过大小限制"},
    422: {
        "model": ErrorResponse,
        "description": "文件格式 / 解析失败，或该 JD 还没有评分标准",
    },
}


@router.get(
    "",
    response_model=ResumeEvaluationListResponse,
    summary="分页查询简历筛选记录",
    description="返回启用中的简历记录，按上传时间倒序；支持候选人、文件名、 JD 与状态筛选。",
    responses=_RESUME_ERROR_RESPONSES,
)
async def list_resume_evaluations(
    _current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=100, description="每页数量"),
    keyword: str | None = Query(None, max_length=100, description="姓名 / 文件名 / 岗位关键字"),
    status: ResumeStatus | None = Query(None, description="复核状态"),
    job_description_id: UUID | None = Query(None, description="关联 JD ID"),
) -> ResumeEvaluationListResponse:
    """分页查询简历筛选记录。"""
    records, total = await resume_evaluation_service.list_resume_evaluations(
        db,
        page=page,
        page_size=page_size,
        keyword=keyword,
        status=status,
        job_description_id=job_description_id,
    )
    return ResumeEvaluationListResponse(
        items=[resume_evaluation_service.to_list_item(record) for record in records],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/upload",
    response_model=ResumeEvaluationRead,
    status_code=201,
    summary="上传简历并评分",
    description=(
        "上传 PDF / DOC / DOCX / TXT 简历，按所选 JD 最新的一份评分标准调用 Dify "
        "type=3 完成评分并保存。该 JD 没有评分标准时返回 422，不发起评分。"
    ),
    responses={
        **_RESUME_ERROR_RESPONSES,
        502: {"model": ErrorResponse, "description": "Dify 鉴权失败、工作流失败或返回异常"},
        503: {"model": ErrorResponse, "description": "Dify 未配置、不可达或超时"},
    },
)
async def upload_resume(
    current_user: CurrentUser,
    client: DifyClient,
    file: UploadFile = File(..., description="简历文件（PDF / DOC / DOCX / TXT）"),
    job_description_id: UUID = Form(..., description="用于匹配的 JD ID"),
    db: AsyncSession = Depends(get_db),
) -> ResumeEvaluationRead:
    """上传简历并同步完成 AI 评分。"""
    max_bytes = settings.resume_max_file_size_mb * 1024 * 1024
    if file.size is not None and file.size > max_bytes:
        raise ResumeTooLargeError(
            f"简历文件不能超过 {settings.resume_max_file_size_mb}MB",
            details={"max_size_mb": settings.resume_max_file_size_mb, "file_size": file.size},
        )
    content = await file.read()
    record = await resume_evaluation_service.evaluate_resume(
        db,
        filename=file.filename or "",
        content=content,
        job_description_id=job_description_id,
        user_id=current_user.id,
        client=client,
    )
    return resume_evaluation_service.to_read(record)


@router.get(
    "/{evaluation_id}",
    response_model=ResumeEvaluationRead,
    summary="获取简历筛选详情",
    description="返回候选人基础信息、完整简历正文、总分与各维度评分理由。",
    responses=_RESUME_ERROR_RESPONSES,
)
async def get_resume_evaluation(
    evaluation_id: UUID,
    _current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ResumeEvaluationRead:
    """获取简历筛选详情。"""
    record = await resume_evaluation_service.get_resume_evaluation(db, evaluation_id)
    return resume_evaluation_service.to_read(record)


@router.patch(
    "/{evaluation_id}/status",
    response_model=ResumeEvaluationRead,
    summary="更新简历复核状态",
    description="人工把简历标记为待复核、进入面试或淘汰。",
    responses=_RESUME_ERROR_RESPONSES,
)
async def update_resume_status(
    evaluation_id: UUID,
    payload: ResumeEvaluationStatusUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ResumeEvaluationRead:
    """更新简历复核状态。"""
    record = await resume_evaluation_service.update_resume_status(
        db,
        evaluation_id,
        payload.status,
        user_id=current_user.id,
    )
    return resume_evaluation_service.to_read(record)
