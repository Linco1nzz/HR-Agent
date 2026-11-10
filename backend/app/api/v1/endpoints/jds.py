"""JD 接口：列表、详情、创建、编辑与 AI 生成。

接口层只处理参数与响应组装；查询 / 落库 / Dify 调用位于
:mod:`app.services.jd_service`。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DifyClient
from app.db.session import get_db
from app.schemas.error import ErrorResponse
from app.schemas.jd import (
    GenerateJDRequest,
    GenerateJDResponse,
    JDStatus,
    JobDescriptionCreate,
    JobDescriptionListResponse,
    JobDescriptionRead,
    JobDescriptionUpdate,
)
from app.services import jd_service

router = APIRouter(prefix="/jds", tags=["jds"])

_AUTH_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "缺少令牌、令牌无效或已过期"},
}

_JD_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    **_AUTH_ERROR_RESPONSES,
    404: {"model": ErrorResponse, "description": "JD 不存在"},
    422: {"model": ErrorResponse, "description": "请求参数不合法"},
}


@router.get(
    "",
    response_model=JobDescriptionListResponse,
    summary="分页查询 JD",
    description="返回启用中的 JD，按更新时间倒序；支持标题 / 部门 / 正文关键字与状态筛选。",
    responses=_JD_ERROR_RESPONSES,
)
async def list_jds(
    _current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=100, description="每页数量"),
    keyword: str | None = Query(None, max_length=100, description="标题 / 部门 / 正文关键字"),
    status: JDStatus | None = Query(None, description="状态筛选"),
) -> JobDescriptionListResponse:
    """分页查询 JD 列表。"""
    records, total = await jd_service.list_jds(
        db,
        page=page,
        page_size=page_size,
        keyword=keyword,
        status=status,
    )
    criteria_counts = await jd_service.count_criteria_by_jd(db, [record.id for record in records])
    return JobDescriptionListResponse(
        items=[
            jd_service.to_list_item(record, criteria_counts.get(record.id, 0)) for record in records
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/generate",
    response_model=GenerateJDResponse,
    summary="AI 生成 JD",
    description=(
        "根据职位名称、部门、技能等表单信息调用 Dify Chatflow 的 type=1 分支生成 JD，"
        "结果不直接落库；前端确认后可调用创建接口保存。"
    ),
    responses={
        **_JD_ERROR_RESPONSES,
        502: {"model": ErrorResponse, "description": "Dify 鉴权失败、工作流失败或返回异常"},
        503: {"model": ErrorResponse, "description": "Dify 未配置、不可达或超时"},
    },
)
async def generate_jd(
    payload: GenerateJDRequest,
    current_user: CurrentUser,
    client: DifyClient,
) -> GenerateJDResponse:
    """调用 Dify 生成 JD 正文。"""
    return await jd_service.generate_jd(payload, user_id=current_user.id, client=client)


@router.post(
    "/generate/stream",
    response_class=StreamingResponse,
    response_model=None,
    summary="AI 流式生成 JD",
    description=(
        "与 `/jds/generate` 相同的入参，以 `text/event-stream` 返回归一化事件："
        '`start`、`delta`（`{"content": "..."}`）、`done`（完整 JD）或 '
        "`error`。前端可边接收边渲染，最后把 `done.content` 保存。"
    ),
    responses={
        **_JD_ERROR_RESPONSES,
        200: {
            "description": "SSE 事件流",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
        502: {"model": ErrorResponse, "description": "Dify 鉴权失败、工作流失败或返回异常"},
        503: {"model": ErrorResponse, "description": "Dify 未配置、不可达或超时"},
    },
)
async def stream_generate_jd(
    payload: GenerateJDRequest,
    current_user: CurrentUser,
    client: DifyClient,
) -> StreamingResponse:
    """流式生成 JD；校验失败会在建立流之前返回统一 JSON 错误。"""
    events = jd_service.stream_generate_jd(
        payload,
        user_id=current_user.id,
        client=client,
    )
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "",
    response_model=JobDescriptionRead,
    status_code=201,
    summary="创建 JD",
    description="保存手动填写或 AI 生成后的 JD；创建人取自当前登录用户。",
    responses=_JD_ERROR_RESPONSES,
)
async def create_jd(
    payload: JobDescriptionCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> JobDescriptionRead:
    """创建 JD。"""
    record = await jd_service.create_jd(db, payload, user_id=current_user.id)
    return JobDescriptionRead.model_validate(record)


@router.get(
    "/{jd_id}",
    response_model=JobDescriptionRead,
    summary="获取 JD 详情",
    description="返回基本信息、技能要求、JD 正文与生成信息。",
    responses=_JD_ERROR_RESPONSES,
)
async def get_jd(
    jd_id: UUID,
    _current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> JobDescriptionRead:
    """获取 JD 详情。"""
    record = await jd_service.get_jd(db, jd_id)
    return JobDescriptionRead.model_validate(record)


@router.patch(
    "/{jd_id}",
    response_model=JobDescriptionRead,
    summary="编辑 JD",
    description="局部更新 JD；只修改请求中显式传入的字段。",
    responses=_JD_ERROR_RESPONSES,
)
async def update_jd(
    jd_id: UUID,
    payload: JobDescriptionUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> JobDescriptionRead:
    """编辑 JD。"""
    record = await jd_service.update_jd(db, jd_id, payload, user_id=current_user.id)
    return JobDescriptionRead.model_validate(record)
