"""智能面试方案接口：流式生成、保存、编辑、列表、详情与导出。

接口层只做鉴权、参数校验与响应组装；生成、落库与导出格式转换分别位于
:mod:`app.services.interview_plan_service` 与
:mod:`app.services.interview_plan_export`。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DifyClient
from app.api.v1.responses import sse_response
from app.db.session import get_db
from app.schemas.error import ErrorResponse
from app.schemas.interview_plan import (
    ExportFormat,
    GenerateInterviewPlanRequest,
    InterviewPlanCreate,
    InterviewPlanListResponse,
    InterviewPlanRead,
    InterviewPlanUpdate,
)
from app.services import interview_plan_export, interview_plan_service

router = APIRouter(prefix="/interview-plans", tags=["interview-plans"])

_AUTH_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "缺少令牌、令牌无效或已过期"},
}

_INTERVIEW_PLAN_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    **_AUTH_ERROR_RESPONSES,
    404: {"model": ErrorResponse, "description": "面试方案、简历记录或关联 JD 不存在"},
    422: {"model": ErrorResponse, "description": "请求参数不合法"},
}

_DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_MARKDOWN_MEDIA_TYPE = "text/markdown; charset=utf-8"


@router.get(
    "",
    response_model=InterviewPlanListResponse,
    summary="分页查询面试方案",
    description="返回启用中的面试方案，按创建时间倒序；可按简历评价记录筛选。",
    responses=_INTERVIEW_PLAN_ERROR_RESPONSES,
)
async def list_interview_plans(
    _current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=100, description="每页数量"),
    resume_evaluation_id: UUID | None = Query(None, description="关联的简历评价 ID"),
    keyword: str | None = Query(None, max_length=100, description="候选人 / 岗位 / JD 关键字"),
) -> InterviewPlanListResponse:
    """分页查询面试方案列表。"""
    records, total = await interview_plan_service.list_interview_plans(
        db,
        page=page,
        page_size=page_size,
        resume_evaluation_id=resume_evaluation_id,
        keyword=keyword,
    )
    return InterviewPlanListResponse(
        items=[interview_plan_service.to_list_item(record) for record in records],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/generate/stream",
    response_class=StreamingResponse,
    response_model=None,
    summary="AI 流式生成面试方案",
    description=(
        "根据简历评价记录关联的简历与 JD 调用 Dify type=4，以 `text/event-stream` "
        '返回归一化事件：`start`、`delta`（`{"content": "..."}`）、`done`（完整方案）'
        "或 `error`。生成结果不落库，前端确认后调用保存接口。"
    ),
    responses={
        **_INTERVIEW_PLAN_ERROR_RESPONSES,
        200: {
            "description": "SSE 事件流",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
        502: {"model": ErrorResponse, "description": "Dify 鉴权失败、工作流失败或返回异常"},
        503: {"model": ErrorResponse, "description": "Dify 未配置、不可达或超时"},
    },
)
async def stream_generate_interview_plan(
    payload: GenerateInterviewPlanRequest,
    current_user: CurrentUser,
    client: DifyClient,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """流式生成面试方案；简历或 JD 校验失败会在建立流之前返回统一 JSON 错误。"""
    return sse_response(
        await interview_plan_service.stream_generate_interview_plan(
            db,
            payload,
            user_id=current_user.id,
            client=client,
        )
    )


@router.post(
    "",
    response_model=InterviewPlanRead,
    status_code=201,
    summary="保存面试方案",
    description="保存生成后或手动填写的面试方案；关联 JD 信息取自简历评价记录快照。",
    responses=_INTERVIEW_PLAN_ERROR_RESPONSES,
)
async def create_interview_plan(
    payload: InterviewPlanCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> InterviewPlanRead:
    """创建面试方案。"""
    record = await interview_plan_service.create_interview_plan(
        db,
        payload,
        user_id=current_user.id,
    )
    return InterviewPlanRead.model_validate(record)


@router.get(
    "/{plan_id}",
    response_model=InterviewPlanRead,
    summary="获取面试方案详情",
    description="返回候选人信息、完整面试方案正文与生成信息。",
    responses=_INTERVIEW_PLAN_ERROR_RESPONSES,
)
async def get_interview_plan(
    plan_id: UUID,
    _current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> InterviewPlanRead:
    """获取面试方案详情。"""
    record = await interview_plan_service.get_interview_plan(db, plan_id)
    return InterviewPlanRead.model_validate(record)


@router.patch(
    "/{plan_id}",
    response_model=InterviewPlanRead,
    summary="编辑面试方案",
    description="局部更新候选人信息或面试方案正文；只修改请求中显式传入的字段。",
    responses=_INTERVIEW_PLAN_ERROR_RESPONSES,
)
async def update_interview_plan(
    plan_id: UUID,
    payload: InterviewPlanUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> InterviewPlanRead:
    """编辑面试方案。"""
    record = await interview_plan_service.update_interview_plan(
        db,
        plan_id,
        payload,
        user_id=current_user.id,
    )
    return InterviewPlanRead.model_validate(record)


@router.get(
    "/{plan_id}/export",
    response_class=Response,
    response_model=None,
    summary="导出面试方案",
    description="按 `format` 导出 Word（默认）或 Markdown 文件，文件名包含候选人姓名与日期。",
    responses={
        **_INTERVIEW_PLAN_ERROR_RESPONSES,
        200: {
            "description": "面试方案文件",
            "content": {
                _DOCX_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}},
                "text/markdown": {"schema": {"type": "string"}},
            },
        },
    },
)
async def export_interview_plan(
    plan_id: UUID,
    _current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    export_format: ExportFormat = Query(
        ExportFormat.DOCX,
        alias="format",
        description="导出格式：docx（默认）或 markdown",
    ),
) -> Response:
    """导出面试方案文件。"""
    record = await interview_plan_service.get_interview_plan(db, plan_id)
    if export_format is ExportFormat.MARKDOWN:
        content = interview_plan_export.build_markdown(record).encode("utf-8")
        media_type = _MARKDOWN_MEDIA_TYPE
    else:
        content = interview_plan_export.build_docx(record)
        media_type = _DOCX_MEDIA_TYPE

    filename = interview_plan_export.build_filename(record, export_format)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": interview_plan_export.content_disposition(filename)},
    )
