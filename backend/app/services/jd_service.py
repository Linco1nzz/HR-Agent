"""JD 业务逻辑：列表、详情、创建、更新与 AI 生成。

AI 生成复用 :mod:`app.services.dify_service` 的 Chatflow type=1 分支；生成结果
只返回给调用方，是否落库由前端确认后调用创建 / 更新接口决定。
"""

from __future__ import annotations

import json
import re
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
from app.schemas.jd import (
    GenerateJDRequest,
    GenerateJDResponse,
    JDStatus,
    JobDescriptionCreate,
    JobDescriptionListItem,
    JobDescriptionUpdate,
)
from app.services import dify_service

logger = get_logger(__name__)

_PREVIEW_LENGTH = 140


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
async def list_jds(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    keyword: str | None = None,
    status: JDStatus | None = None,
) -> tuple[list[JobDescription], int]:
    """分页查询启用中的 JD，按更新时间倒序。"""
    filters: list[ColumnElement[bool]] = [JobDescription.is_active.is_(True)]

    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        filters.append(
            or_(
                JobDescription.title.ilike(pattern),
                JobDescription.department.ilike(pattern),
                JobDescription.content.ilike(pattern),
            )
        )
    if status is not None:
        filters.append(JobDescription.status == status.value)

    total = await db.scalar(select(func.count()).select_from(JobDescription).where(*filters)) or 0
    stmt = (
        select(JobDescription)
        .where(*filters)
        .order_by(JobDescription.updated_at.desc(), JobDescription.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.scalars(stmt)).all()
    return list(rows), total


async def get_jd(db: AsyncSession, jd_id: UUID) -> JobDescription:
    """按 ID 获取启用中的 JD，不存在时抛 404。"""
    record = await db.get(JobDescription, jd_id)
    if record is None or not record.is_active:
        raise NotFoundError("JD 不存在", details={"jd_id": str(jd_id)})
    return record


# ---------------------------------------------------------------------------
# 创建 / 更新
# ---------------------------------------------------------------------------
async def create_jd(
    db: AsyncSession,
    payload: JobDescriptionCreate,
    *,
    user_id: UUID,
) -> JobDescription:
    """创建 JD 并标记创建人。"""
    record = JobDescription(**payload.model_dump())
    record.created_by = user_id
    db.add(record)
    await db.commit()
    await db.refresh(record)
    logger.info("jd_created", jd_id=str(record.id), user_id=str(user_id), status=record.status)
    return record


async def update_jd(
    db: AsyncSession,
    jd_id: UUID,
    payload: JobDescriptionUpdate,
    *,
    user_id: UUID,
) -> JobDescription:
    """局部更新 JD；只处理请求中显式传入的字段。"""
    record = await get_jd(db, jd_id)
    data = payload.model_dump(exclude_unset=True)

    for field in ("title", "content", "status", "workflow_type"):
        if field in data and data[field] is None:
            raise WorkflowValidationError(
                f"{field} 不能为 null",
                details={"field": field},
            )

    for field, value in data.items():
        setattr(record, field, value)
    record.updated_by = user_id

    await db.commit()
    await db.refresh(record)
    logger.info("jd_updated", jd_id=str(record.id), user_id=str(user_id), fields=sorted(data))
    return record


_FENCED_CODE = re.compile(r"```.*?```", re.DOTALL)
_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_BOLD = re.compile(r"(\*\*|__)(.+?)\1")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_LIST_MARKER = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_ORDERED_MARKER = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)


def strip_markdown(text: str) -> str:
    """把 Markdown 转成适合列表摘要的纯文本（只做轻量清理）。"""
    plain = _FENCED_CODE.sub(" ", text)
    plain = _HEADING.sub("", plain)
    plain = _BOLD.sub(r"\2", plain)
    plain = _INLINE_CODE.sub(r"\1", plain)
    plain = _LIST_MARKER.sub("\u2022 ", plain)
    plain = _ORDERED_MARKER.sub("", plain)
    return re.sub(r"\s+", " ", plain).strip()


def to_list_item(record: JobDescription, criteria_count: int = 0) -> JobDescriptionListItem:
    """把 ORM 记录转换为列表项，并生成去格式 / 去换行的正文摘要。"""
    preview = strip_markdown(record.content)
    # 正文通常以标题开头，列表里已经展示过标题，避免摘要重复
    if preview.startswith(record.title):
        preview = preview[len(record.title) :].lstrip(" -—:：")
    if len(preview) > _PREVIEW_LENGTH:
        preview = f"{preview[:_PREVIEW_LENGTH].rstrip()}…"
    return JobDescriptionListItem(
        id=record.id,
        title=record.title,
        department=record.department,
        location=record.location,
        salary_range=record.salary_range,
        experience_level=record.experience_level,
        education=record.education,
        job_type=record.job_type,
        skills=record.skills,
        status=JDStatus(record.status),
        criteria_count=criteria_count,
        content_preview=preview,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


async def count_criteria_by_jd(
    db: AsyncSession,
    jd_ids: list[UUID],
) -> dict[UUID, int]:
    """批量统计每个 JD 关联的启用中评分标准数量，供列表展示。"""
    if not jd_ids:
        return {}
    stmt = (
        select(ScoringCriteria.job_description_id, func.count())
        .where(
            ScoringCriteria.is_active.is_(True),
            ScoringCriteria.job_description_id.in_(jd_ids),
        )
        .group_by(ScoringCriteria.job_description_id)
    )
    rows = (await db.execute(stmt)).all()
    return {row[0]: int(row[1]) for row in rows if row[0] is not None}


# ---------------------------------------------------------------------------
# AI 生成
# ---------------------------------------------------------------------------
def build_generation_query(payload: GenerateJDRequest) -> str:
    """把结构化表单拼成给 Dify type=1 分支的自然语言需求。"""
    lines = [
        "请根据以下岗位信息生成一份完整、专业的职位描述（JD）。",
        f"职位名称必须严格使用“{payload.title}”，不要修改或添加其他职位名称。",
        "请使用 Markdown 输出，包含岗位职责、任职要求、技能要求等部分。",
        "",
        "岗位信息：",
        f"- 职位名称：{payload.title}",
    ]

    optional_fields = (
        ("所属部门", payload.department),
        ("工作地点", payload.location),
        ("薪资范围", payload.salary_range),
        ("经验等级", payload.experience_level),
        ("学历要求", payload.education),
        ("工作类型", payload.job_type),
    )
    lines.extend(f"- {label}: {value}" for label, value in optional_fields if value)
    if payload.skills:
        lines.append(f"- 技能要求：{'、'.join(payload.skills)}")
    if payload.requirements:
        lines.extend(["", "职位要求 / 补充说明：", payload.requirements])
    return "\n".join(lines)


def _build_chat_request(payload: GenerateJDRequest) -> ChatRequest:
    """组装 type=1 的 Chatflow 请求。

    type=1 的 Dify 提示词只使用 ``sys.query``，全部表单信息已拼进 query；
    不再额外传 jobName / jobResponsibilities，避免触发开始节点的长度限制。
    """
    return ChatRequest(
        type=WorkflowType.JD_GENERATION,
        query=build_generation_query(payload),
        auto_generate_name=False,
    )


async def generate_jd(
    payload: GenerateJDRequest,
    *,
    user_id: UUID | str,
    client: httpx.AsyncClient | None = None,
) -> GenerateJDResponse:
    """调用 Dify type=1 生成 JD 正文（阻塞，不落库）。"""
    request = _build_chat_request(payload)
    response = await dify_service.chat(request, user_id=user_id, client=client)
    content = response.answer.strip()
    if not content:
        raise DifyInvalidResponseError("Dify 未返回 JD 内容")

    logger.info(
        "jd_generated",
        user_id=str(user_id),
        content_chars=len(content),
        conversation_id=response.conversation_id,
    )
    return GenerateJDResponse(
        content=content,
        conversation_id=response.conversation_id,
        workflow_type="jd_generation",
        task_id=response.task_id,
        usage=response.usage,
    )


def _sse(event: str, data: dict[str, Any]) -> bytes:
    """编码一个标准 SSE 帧（event + 单行 JSON data）。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


def stream_generate_jd(
    payload: GenerateJDRequest,
    *,
    user_id: UUID | str,
    client: httpx.AsyncClient | None = None,
) -> AsyncIterator[bytes]:
    """真实流式生成 JD。

    返回归一化事件，不把 Dify 的 ``workflow_*`` / ``ping`` 原样暴露给前端：

    - ``start``：流已建立；
    - ``delta``：增量文本 ``{"content": "..."}``；
    - ``done``：完整结果，字段同 ``GenerateJDResponse``；
    - ``error``：``{"status", "code", "message"}``。

    校验、客户端创建等前置错误在返回生成器前抛出；进入流式响应后，Dify 的
    4xx/5xx、超时与断连都转为 ``error`` 事件。
    """
    request = _build_chat_request(payload)
    http = client or dify_service.get_client()
    return _stream_generate_jd_events(http, request, user_id)


async def _stream_generate_jd_events(
    http: httpx.AsyncClient,
    request: ChatRequest,
    user_id: UUID | str,
) -> AsyncIterator[bytes]:
    fragments: list[str] = []
    conversation_id = ""
    task_id = ""
    usage: ChatUsage | None = None
    fallback_content = ""

    yield _sse("start", {"workflow_type": "jd_generation"})

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
            "jd_stream_failed",
            code=exc.code.value,
            status_code=exc.status_code,
            user_id=str(user_id),
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
        logger.exception("jd_stream_unexpected_error", user_id=str(user_id))
        yield _sse(
            "error",
            {
                "status": 500,
                "code": "INTERNAL_ERROR",
                "message": "JD 生成失败，请稍后重试",
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
                "message": "Dify 未返回 JD 内容",
            },
        )
        return

    result = GenerateJDResponse(
        content=content,
        conversation_id=conversation_id,
        workflow_type="jd_generation",
        task_id=task_id,
        usage=usage,
    )
    logger.info(
        "jd_stream_finished",
        user_id=str(user_id),
        content_chars=len(content),
        conversation_id=conversation_id,
    )
    yield _sse("done", result.model_dump(mode="json"))
