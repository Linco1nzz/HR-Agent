"""简历评分标准接口：列表、详情、创建、编辑与 AI 生成。

接口层只处理参数与响应组装；查询 / 落库 / Dify 调用位于
:mod:`app.services.scoring_criteria_service`。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DifyClient
from app.api.v1.responses import sse_response
from app.db.session import get_db
from app.schemas.error import ErrorResponse
from app.schemas.scoring_criteria import (
    GenerateScoringCriteriaRequest,
    GenerateScoringCriteriaResponse,
    ScoringCriteriaCreate,
    ScoringCriteriaListResponse,
    ScoringCriteriaRead,
    ScoringCriteriaStatus,
    ScoringCriteriaUpdate,
)
from app.services import scoring_criteria_service

router = APIRouter(prefix="/scoring-criteria", tags=["scoring-criteria"])

_AUTH_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "缺少令牌、令牌无效或已过期"},
}

_SCORING_CRITERIA_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    **_AUTH_ERROR_RESPONSES,
    404: {"model": ErrorResponse, "description": "评分标准或职位描述不存在"},
    422: {"model": ErrorResponse, "description": "请求参数不合法"},
}


@router.get(
    "",
    response_model=ScoringCriteriaListResponse,
    summary="分页查询评分标准",
    description="返回启用中的评分标准，按更新时间倒序；支持关键字、状态与关联 JD 筛选。",
    responses=_SCORING_CRITERIA_ERROR_RESPONSES,
)
async def list_scoring_criteria(
    _current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=100, description="每页数量"),
    keyword: str | None = Query(None, max_length=100, description="标题 / 职位名称 / 正文关键字"),
    status: ScoringCriteriaStatus | None = Query(None, description="状态筛选"),
    job_description_id: UUID | None = Query(None, description="关联的 JD ID"),
) -> ScoringCriteriaListResponse:
    """分页查询评分标准列表。"""
    records, total = await scoring_criteria_service.list_scoring_criteria(
        db,
        page=page,
        page_size=page_size,
        keyword=keyword,
        status=status,
        job_description_id=job_description_id,
    )
    return ScoringCriteriaListResponse(
        items=[scoring_criteria_service.to_list_item(record) for record in records],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/generate",
    response_model=GenerateScoringCriteriaResponse,
    summary="AI 生成简历评分标准",
    description=(
        "根据已保存的 JD 调用 Dify Chatflow 的 type=2 分支生成简历评分标准，"
        "结果不直接落库；前端编辑后可调用创建接口保存。"
    ),
    responses={
        **_SCORING_CRITERIA_ERROR_RESPONSES,
        502: {"model": ErrorResponse, "description": "Dify 鉴权失败、工作流失败或返回异常"},
        503: {"model": ErrorResponse, "description": "Dify 未配置、不可达或超时"},
    },
)
async def generate_scoring_criteria(
    payload: GenerateScoringCriteriaRequest,
    current_user: CurrentUser,
    client: DifyClient,
    db: AsyncSession = Depends(get_db),
) -> GenerateScoringCriteriaResponse:
    """根据已有 JD 生成简历评分标准。"""
    return await scoring_criteria_service.generate_scoring_criteria(
        db,
        payload,
        user_id=current_user.id,
        client=client,
    )


@router.post(
    "/generate/stream",
    response_class=StreamingResponse,
    response_model=None,
    summary="AI 流式生成简历评分标准",
    description=(
        "与 `/scoring-criteria/generate` 相同的入参，以 `text/event-stream` 返回归一化事件："
        '`start`、`delta`（`{"content": "..."}`）、`done`（完整评分标准）或 `error`。'
        "前端可边接收边渲染，最后把 `done.content` 保存。"
    ),
    responses={
        **_SCORING_CRITERIA_ERROR_RESPONSES,
        200: {
            "description": "SSE 事件流",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
        502: {"model": ErrorResponse, "description": "Dify 鉴权失败、工作流失败或返回异常"},
        503: {"model": ErrorResponse, "description": "Dify 未配置、不可达或超时"},
    },
)
async def stream_generate_scoring_criteria(
    payload: GenerateScoringCriteriaRequest,
    current_user: CurrentUser,
    client: DifyClient,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """流式生成简历评分标准；JD 校验失败会在建立流之前返回统一 JSON 错误。"""
    return sse_response(
        await scoring_criteria_service.stream_generate_scoring_criteria(
            db,
            payload,
            user_id=current_user.id,
            client=client,
        )
    )


@router.post(
    "",
    response_model=ScoringCriteriaRead,
    status_code=201,
    summary="创建评分标准",
    description="保存手动编辑或 AI 生成后的简历评分标准；创建人取自当前登录用户。",
    responses=_SCORING_CRITERIA_ERROR_RESPONSES,
)
async def create_scoring_criteria(
    payload: ScoringCriteriaCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ScoringCriteriaRead:
    """创建评分标准。"""
    record = await scoring_criteria_service.create_scoring_criteria(
        db, payload, user_id=current_user.id
    )
    return ScoringCriteriaRead.model_validate(record)


@router.get(
    "/{criteria_id}",
    response_model=ScoringCriteriaRead,
    summary="获取评分标准详情",
    description="返回标题、职位名称、总分、评分维度、正文与生成信息。",
    responses=_SCORING_CRITERIA_ERROR_RESPONSES,
)
async def get_scoring_criteria(
    criteria_id: UUID,
    _current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ScoringCriteriaRead:
    """获取评分标准详情。"""
    record = await scoring_criteria_service.get_scoring_criteria(db, criteria_id)
    return ScoringCriteriaRead.model_validate(record)


@router.patch(
    "/{criteria_id}",
    response_model=ScoringCriteriaRead,
    summary="编辑评分标准",
    description="局部更新评分标准；只修改请求中显式传入的字段。",
    responses=_SCORING_CRITERIA_ERROR_RESPONSES,
)
async def update_scoring_criteria(
    criteria_id: UUID,
    payload: ScoringCriteriaUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ScoringCriteriaRead:
    """编辑评分标准。"""
    record = await scoring_criteria_service.update_scoring_criteria(
        db, criteria_id, payload, user_id=current_user.id
    )
    return ScoringCriteriaRead.model_validate(record)
