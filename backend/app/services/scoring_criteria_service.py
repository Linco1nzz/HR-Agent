"""简历评分标准业务逻辑：列表、详情、创建、更新与 AI 生成。

生成流程复用 :mod:`app.services.dify_service` 的 Chatflow type=2 分支：根据已
保存的 JD 组装 query，调用 Dify 后只返回结果，是否落库由前端确认后调用创建 /
更新接口决定。``job_description_id`` 不建数据库外键，关联有效性在服务层校验。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AppException,
    DifyInvalidResponseError,
    NotFoundError,
    WorkflowValidationError,
)
from app.core.logging import get_logger
from app.db.models import JobDescription, ScoringCriteria
from app.schemas.ai import ChatRequest, ChatUsage, WorkflowType
from app.schemas.scoring_criteria import (
    WORKFLOW_TYPE,
    GenerateScoringCriteriaRequest,
    GenerateScoringCriteriaResponse,
    ScoringCriteriaCreate,
    ScoringCriteriaListItem,
    ScoringCriteriaStatus,
    ScoringCriteriaUpdate,
)
from app.services import dify_service, jd_service

logger = get_logger(__name__)

_PREVIEW_LENGTH = 140
_TITLE_MAX_LENGTH = 255


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
async def list_scoring_criteria(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    keyword: str | None = None,
    status: ScoringCriteriaStatus | None = None,
    job_description_id: UUID | None = None,
) -> tuple[list[ScoringCriteria], int]:
    """分页查询启用中的评分标准，按更新时间倒序。"""
    filters: list[ColumnElement[bool]] = [ScoringCriteria.is_active.is_(True)]

    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        filters.append(
            or_(
                ScoringCriteria.title.ilike(pattern),
                ScoringCriteria.job_title.ilike(pattern),
                ScoringCriteria.content.ilike(pattern),
            )
        )
    if status is not None:
        filters.append(ScoringCriteria.status == status.value)
    if job_description_id is not None:
        filters.append(ScoringCriteria.job_description_id == job_description_id)

    total = await db.scalar(select(func.count()).select_from(ScoringCriteria).where(*filters)) or 0
    stmt = (
        select(ScoringCriteria)
        .where(*filters)
        .order_by(ScoringCriteria.updated_at.desc(), ScoringCriteria.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.scalars(stmt)).all()
    return list(rows), total


async def get_scoring_criteria(db: AsyncSession, criteria_id: UUID) -> ScoringCriteria:
    """按 ID 获取启用中的评分标准，不存在时抛 404。"""
    record = await db.get(ScoringCriteria, criteria_id)
    if record is None or not record.is_active:
        raise NotFoundError("评分标准不存在", details={"criteria_id": str(criteria_id)})
    return record


# ---------------------------------------------------------------------------
# 创建 / 更新
# ---------------------------------------------------------------------------
async def _resolve_job_description(db: AsyncSession, data: dict[str, Any]) -> None:
    """校验并补全 JD 关联；JD 不存在时由 ``jd_service.get_jd`` 抛 404。"""
    jd_id = data.get("job_description_id")
    if jd_id is None:
        return
    jd = await jd_service.get_jd(db, jd_id)
    if not data.get("job_title"):
        data["job_title"] = jd.title


async def create_scoring_criteria(
    db: AsyncSession,
    payload: ScoringCriteriaCreate,
    *,
    user_id: UUID,
) -> ScoringCriteria:
    """创建评分标准并标记创建人。"""
    data = payload.model_dump()
    await _resolve_job_description(db, data)

    record = ScoringCriteria(**data)
    record.created_by = user_id
    db.add(record)
    await db.commit()
    await db.refresh(record)
    logger.info(
        "scoring_criteria_created",
        criteria_id=str(record.id),
        user_id=str(user_id),
        status=record.status,
        job_description_id=str(record.job_description_id) if record.job_description_id else None,
    )
    return record


async def update_scoring_criteria(
    db: AsyncSession,
    criteria_id: UUID,
    payload: ScoringCriteriaUpdate,
    *,
    user_id: UUID,
) -> ScoringCriteria:
    """局部更新评分标准；只处理请求中显式传入的字段。"""
    record = await get_scoring_criteria(db, criteria_id)
    data = payload.model_dump(exclude_unset=True)

    for field in ("title", "content", "status", "total_score", "workflow_type"):
        if field in data and data[field] is None:
            raise WorkflowValidationError(
                f"{field} 不能为 null",
                details={"field": field},
            )

    await _resolve_job_description(db, data)

    for field, value in data.items():
        setattr(record, field, value)
    record.updated_by = user_id

    await db.commit()
    await db.refresh(record)
    logger.info(
        "scoring_criteria_updated",
        criteria_id=str(record.id),
        user_id=str(user_id),
        fields=sorted(data),
    )
    return record


# ---------------------------------------------------------------------------
# 列表展示
# ---------------------------------------------------------------------------
def to_list_item(record: ScoringCriteria) -> ScoringCriteriaListItem:
    """把 ORM 记录转换为列表项，并生成去格式 / 去换行的正文摘要。"""
    preview = jd_service.strip_markdown(record.content)
    # 正文通常以标题开头，列表里已经展示过标题，避免摘要重复
    if preview.startswith(record.title):
        preview = preview[len(record.title) :].lstrip(" -—:：")
    if len(preview) > _PREVIEW_LENGTH:
        preview = f"{preview[:_PREVIEW_LENGTH].rstrip()}…"

    return ScoringCriteriaListItem(
        id=record.id,
        title=record.title,
        job_title=record.job_title,
        total_score=record.total_score,
        status=ScoringCriteriaStatus(record.status),
        job_description_id=record.job_description_id,
        dimension_count=len(record.scoring_dimensions or []),
        content_preview=preview,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


# ---------------------------------------------------------------------------
# AI 生成
# ---------------------------------------------------------------------------
def build_generation_query(
    jd: JobDescription,
    *,
    total_score: str = "100",
    instructions: str | None = None,
) -> str:
    """把已保存的 JD 拼成给 Dify type=2 分支的自然语言需求。"""
    lines = [
        "请根据以下职位描述（JD）生成一份可直接用于简历筛选的评分标准。",
        f"要求：采用 {total_score} 分制，至少包含 4 个评分维度；"
        "每个维度给出分值或权重、考察要点和评分说明。",
        "请使用 Markdown 输出，包含评分维度总览表和每个维度的评分细则。",
        "",
        f"职位名称：{jd.title}",
    ]

    optional_fields = (
        ("所属部门", jd.department),
        ("工作地点", jd.location),
        ("经验等级", jd.experience_level),
        ("学历要求", jd.education),
    )
    lines.extend(f"{label}：{value}" for label, value in optional_fields if value)
    if jd.skills:
        lines.append(f"技能要求：{'、'.join(jd.skills)}")

    lines.extend(["", "职位描述：", jd.content])
    if jd.requirements:
        lines.extend(["", "职位要求：", jd.requirements])
    if instructions:
        lines.extend(["", "额外要求：", instructions])
    return "\n".join(lines)


def _build_chat_request(
    jd: JobDescription,
    *,
    total_score: str,
    instructions: str | None,
) -> ChatRequest:
    """组装 type=2 的 Chatflow 请求；与 type=1 一样只使用 ``sys.query``。"""
    return ChatRequest(
        type=WorkflowType.RESUME_CRITERIA,
        query=build_generation_query(jd, total_score=total_score, instructions=instructions),
        auto_generate_name=False,
    )


async def generate_scoring_criteria(
    db: AsyncSession,
    payload: GenerateScoringCriteriaRequest,
    *,
    user_id: UUID | str,
    client: httpx.AsyncClient | None = None,
) -> GenerateScoringCriteriaResponse:
    """根据已有 JD 调用 Dify type=2 生成评分标准（阻塞，不落库）。"""
    jd = await jd_service.get_jd(db, payload.job_description_id)
    request = _build_chat_request(
        jd,
        total_score=payload.total_score,
        instructions=payload.instructions,
    )
    response = await dify_service.chat(request, user_id=user_id, client=client)

    content = response.answer.strip()
    if not content:
        raise DifyInvalidResponseError("Dify 未返回简历评分标准内容")

    logger.info(
        "scoring_criteria_generated",
        user_id=str(user_id),
        job_description_id=str(jd.id),
        content_chars=len(content),
        conversation_id=response.conversation_id,
    )
    return _build_generation_result(
        jd,
        payload,
        content=content,
        conversation_id=response.conversation_id,
        task_id=response.task_id,
        usage=response.usage,
    )


def _build_generation_result(
    jd: JobDescription,
    payload: GenerateScoringCriteriaRequest,
    *,
    content: str,
    conversation_id: str,
    task_id: str,
    usage: ChatUsage | None,
) -> GenerateScoringCriteriaResponse:
    """组装阻塞 / 流式共用的生成结果。"""
    title = payload.title or f"{jd.title} - 简历评分标准"
    # JD 标题允许 255 字符，拼接后缀后需要截断，避免保存时触发 schema 长度校验
    title = title[:_TITLE_MAX_LENGTH]
    return GenerateScoringCriteriaResponse(
        title=title,
        job_title=jd.title,
        content=content,
        total_score=payload.total_score,
        job_description_id=jd.id,
        conversation_id=conversation_id,
        workflow_type=WORKFLOW_TYPE,
        task_id=task_id,
        usage=usage,
    )


def _sse(event: str, data: dict[str, Any]) -> bytes:
    """编码一个标准 SSE 帧（event + 单行 JSON data）。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


async def stream_generate_scoring_criteria(
    db: AsyncSession,
    payload: GenerateScoringCriteriaRequest,
    *,
    user_id: UUID | str,
    client: httpx.AsyncClient | None = None,
) -> AsyncIterator[bytes]:
    """真实流式生成简历评分标准。

    先加载 JD 并组装 type=2 请求，再把 Dify SSE 归一化为：

    - ``start``：流已建立；
    - ``delta``：增量文本 ``{"content": "..."}``；
    - ``done``：完整结果，字段同 ``GenerateScoringCriteriaResponse``；
    - ``error``：``{"status", "code", "message"}``。

    JD 不存在、Dify 未配置等前置错误在返回生成器前抛出；进入流式响应后，
    Dify 的 4xx/5xx、超时与断连都转为 ``error`` 事件。
    """
    jd = await jd_service.get_jd(db, payload.job_description_id)
    request = _build_chat_request(
        jd,
        total_score=payload.total_score,
        instructions=payload.instructions,
    )
    http = client or dify_service.get_client()
    return _stream_scoring_criteria_events(http, request, jd, payload, user_id)


async def _stream_scoring_criteria_events(
    http: httpx.AsyncClient,
    request: ChatRequest,
    jd: JobDescription,
    payload: GenerateScoringCriteriaRequest,
    user_id: UUID | str,
) -> AsyncIterator[bytes]:
    fragments: list[str] = []
    conversation_id = ""
    task_id = ""
    usage: ChatUsage | None = None
    fallback_content = ""

    yield _sse("start", {"workflow_type": WORKFLOW_TYPE})

    try:
        async for event in dify_service.iter_stream_events(
            request,
            user_id=user_id,
            client=http,
        ):
            kind = event.get("event")
            if isinstance(event.get("conversation_id"), str):
                conversation_id = event["conversation_id"]
            if isinstance(event.get("task_id"), str):
                task_id = event["task_id"]

            if kind == "message":
                delta = event.get("answer")
                if isinstance(delta, str) and delta:
                    fragments.append(delta)
                    yield _sse("delta", {"content": delta})
            elif kind == "message_end":
                metadata = event.get("metadata")
                if isinstance(metadata, dict):
                    raw_usage = metadata.get("usage")
                    if isinstance(raw_usage, dict):
                        usage = ChatUsage.model_validate(raw_usage)
            elif kind == "workflow_finished":
                data = event.get("data")
                if isinstance(data, dict):
                    outputs = data.get("outputs")
                    if isinstance(outputs, dict) and isinstance(outputs.get("answer"), str):
                        fallback_content = outputs["answer"]
            elif kind == "error":
                yield _sse(
                    "error",
                    {
                        "status": event.get("status", 502),
                        "code": event.get("code", "DIFY_WORKFLOW_FAILED"),
                        "message": event.get("message", "Dify 工作流执行失败"),
                    },
                )
                return
    except AppException as exc:
        logger.warning(
            "scoring_criteria_stream_failed",
            code=exc.code.value,
            status_code=exc.status_code,
            user_id=str(user_id),
            job_description_id=str(jd.id),
        )
        yield _sse(
            "error",
            {
                "status": exc.status_code,
                "code": exc.code.value,
                "message": exc.message,
            },
        )
        return
    except Exception:
        logger.exception(
            "scoring_criteria_stream_unexpected_error",
            user_id=str(user_id),
            job_description_id=str(jd.id),
        )
        yield _sse(
            "error",
            {
                "status": 500,
                "code": "INTERNAL_ERROR",
                "message": "评分标准生成失败，请稍后重试",
            },
        )
        return

    content = "".join(fragments).strip() or fallback_content.strip()
    if not content:
        yield _sse(
            "error",
            {
                "status": 502,
                "code": "DIFY_INVALID_RESPONSE",
                "message": "Dify 未返回简历评分标准内容",
            },
        )
        return

    result = _build_generation_result(
        jd,
        payload,
        content=content,
        conversation_id=conversation_id,
        task_id=task_id,
        usage=usage,
    )
    logger.info(
        "scoring_criteria_stream_finished",
        user_id=str(user_id),
        job_description_id=str(jd.id),
        content_chars=len(content),
        conversation_id=conversation_id,
    )
    yield _sse("done", result.model_dump(mode="json"))
