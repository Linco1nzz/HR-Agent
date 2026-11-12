"""智能面试业务逻辑：按简历与 JD 生成面试方案，以及保存、编辑与查询。

生成流程复用 :mod:`app.services.dify_service` 的 Chatflow type=4 分支：以简历评价
记录关联的简历正文与 JD 组装请求，结果先返回前端预览 / 编辑，确认后再保存。
``resume_evaluation_id`` 不建数据库外键，关联有效性在服务层校验；导出格式转换位于
:mod:`app.services.interview_plan_export`。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import partial
from pathlib import Path
from uuid import UUID

import httpx
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, WorkflowValidationError
from app.core.logging import get_logger
from app.db.models import InterviewPlan, JobDescription, ResumeEvaluation
from app.schemas.ai import ChatRequest, WorkflowType
from app.schemas.interview_plan import (
    WORKFLOW_TYPE,
    GenerateInterviewPlanRequest,
    GenerateInterviewPlanResponse,
    InterviewPlanCreate,
    InterviewPlanListItem,
    InterviewPlanUpdate,
)
from app.services import dify_service, jd_service, resume_evaluation_service
from app.services.streaming import ChatflowResult, stream_chatflow

logger = get_logger(__name__)

_PREVIEW_LENGTH = 140
#: 与 Dify 开始节点 max_length 对齐
_MAX_JD_CHARS = 48_000
_MAX_RESUME_CHARS = 80_000


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
async def list_interview_plans(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    resume_evaluation_id: UUID | None = None,
    keyword: str | None = None,
) -> tuple[list[InterviewPlan], int]:
    """分页查询启用中的面试方案，按创建时间倒序。"""
    filters: list[ColumnElement[bool]] = [InterviewPlan.is_active.is_(True)]

    if resume_evaluation_id is not None:
        filters.append(InterviewPlan.resume_evaluation_id == resume_evaluation_id)
    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        filters.append(
            or_(
                InterviewPlan.candidate_name.ilike(pattern),
                InterviewPlan.candidate_position.ilike(pattern),
                InterviewPlan.job_title.ilike(pattern),
            )
        )

    total = await db.scalar(select(func.count()).select_from(InterviewPlan).where(*filters)) or 0
    stmt = (
        select(InterviewPlan)
        .where(*filters)
        .order_by(InterviewPlan.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.scalars(stmt)).all()
    return list(rows), total


async def get_interview_plan(db: AsyncSession, plan_id: UUID) -> InterviewPlan:
    """按 ID 获取启用中的面试方案，不存在时抛 404。"""
    record = await db.get(InterviewPlan, plan_id)
    if record is None or not record.is_active:
        raise NotFoundError("面试方案不存在", details={"interview_plan_id": str(plan_id)})
    return record


# ---------------------------------------------------------------------------
# 创建 / 更新
# ---------------------------------------------------------------------------
async def create_interview_plan(
    db: AsyncSession,
    payload: InterviewPlanCreate,
    *,
    user_id: UUID,
) -> InterviewPlan:
    """保存面试方案，并从简历评价记录快照关联 JD 信息。"""
    evaluation = await resume_evaluation_service.get_resume_evaluation(
        db,
        payload.resume_evaluation_id,
    )
    record = InterviewPlan(
        candidate_name=payload.candidate_name,
        candidate_position=payload.candidate_position,
        content=payload.content,
        resume_evaluation_id=evaluation.id,
        job_title=evaluation.job_title,
        job_description_id=evaluation.job_description_id,
        conversation_id=payload.conversation_id,
        workflow_type=WORKFLOW_TYPE,
        meta_data=payload.meta_data,
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    logger.info(
        "interview_plan_created",
        interview_plan_id=str(record.id),
        resume_evaluation_id=str(evaluation.id),
        user_id=str(user_id),
        content_chars=len(record.content),
    )
    return record


async def update_interview_plan(
    db: AsyncSession,
    plan_id: UUID,
    payload: InterviewPlanUpdate,
    *,
    user_id: UUID,
) -> InterviewPlan:
    """局部更新面试方案；只处理请求中显式传入的字段。"""
    record = await get_interview_plan(db, plan_id)
    data = payload.model_dump(exclude_unset=True)

    for field in ("candidate_name", "candidate_position", "content"):
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
    logger.info(
        "interview_plan_updated",
        interview_plan_id=str(record.id),
        user_id=str(user_id),
        fields=sorted(data),
    )
    return record


# ---------------------------------------------------------------------------
# AI 生成
# ---------------------------------------------------------------------------
def _candidate_name(evaluation: ResumeEvaluation) -> str:
    """候选人姓名为空时回退到简历文件名，保证方案标题可读。"""
    name = (evaluation.candidate_name or "").strip()
    if name:
        return name[:100]
    stem = Path(evaluation.original_filename or "").stem.strip()
    return (stem or "候选人")[:100]


def _candidate_position(evaluation: ResumeEvaluation, jd: JobDescription) -> str:
    position = (evaluation.candidate_position or "").strip()
    if position:
        return position[:200]
    return (jd.title or "未指定岗位")[:200]


def summarize_jd(jd: JobDescription) -> str:
    """把 JD 的结构化字段与正文拼成给 Dify 的 ``jd`` 输入。"""
    lines = [f"职位名称：{jd.title}"]
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
    return "\n".join(lines)[:_MAX_JD_CHARS]


def build_generation_request(
    evaluation: ResumeEvaluation,
    jd: JobDescription,
    instructions: str | None = None,
) -> ChatRequest:
    """组装 Dify type=4 请求：``jd`` 与 ``jianli`` 为必填输入。"""
    return ChatRequest(
        type=WorkflowType.INTERVIEW_PLAN,
        query=instructions or "",
        inputs={
            "jd": summarize_jd(jd),
            "jianli": evaluation.resume_content[:_MAX_RESUME_CHARS],
        },
        auto_generate_name=False,
    )


def _build_generation_result(
    evaluation: ResumeEvaluation,
    jd: JobDescription,
    result: ChatflowResult,
) -> GenerateInterviewPlanResponse:
    """组装流式 ``done`` 事件中的完整结果。"""
    return GenerateInterviewPlanResponse(
        content=result.content,
        candidate_name=_candidate_name(evaluation),
        candidate_position=_candidate_position(evaluation, jd),
        resume_evaluation_id=evaluation.id,
        job_title=jd.title,
        job_description_id=jd.id,
        conversation_id=result.conversation_id,
        workflow_type=WORKFLOW_TYPE,
        task_id=result.task_id,
        usage=result.usage,
    )


async def stream_generate_interview_plan(
    db: AsyncSession,
    payload: GenerateInterviewPlanRequest,
    *,
    user_id: UUID | str,
    client: httpx.AsyncClient | None = None,
) -> AsyncIterator[bytes]:
    """流式生成面试方案（归一化为 start / delta / done / error 事件）。

    简历记录、JD 不存在或 Dify 未配置等前置错误在返回生成器前抛出；进入流式
    响应后，Dify 的 4xx/5xx、超时与断连都转为 ``error`` 事件。
    """
    evaluation = await resume_evaluation_service.get_resume_evaluation(
        db,
        payload.resume_evaluation_id,
    )
    jd = await jd_service.get_jd(db, evaluation.job_description_id)
    request = build_generation_request(evaluation, jd, payload.instructions)
    http = client or dify_service.get_client()
    return stream_chatflow(
        request,
        user_id=user_id,
        client=http,
        workflow_type=WORKFLOW_TYPE,
        build_result=partial(_build_generation_result, evaluation, jd),
        empty_message="Dify 未返回面试方案内容",
        failure_message="面试方案生成失败，请稍后重试",
        log_context={
            "resume_evaluation_id": str(evaluation.id),
            "job_description_id": str(jd.id),
        },
    )


# ---------------------------------------------------------------------------
# 列表展示
# ---------------------------------------------------------------------------
def to_list_item(record: InterviewPlan) -> InterviewPlanListItem:
    """把 ORM 记录转换为列表项，并生成去格式 / 去换行的正文摘要。"""
    preview = jd_service.strip_markdown(record.content)
    if preview.startswith(record.candidate_name):
        preview = preview[len(record.candidate_name) :].lstrip(" -—:：")
    if len(preview) > _PREVIEW_LENGTH:
        preview = f"{preview[:_PREVIEW_LENGTH].rstrip()}…"

    return InterviewPlanListItem(
        id=record.id,
        candidate_name=record.candidate_name,
        candidate_position=record.candidate_position,
        resume_evaluation_id=record.resume_evaluation_id,
        job_title=record.job_title,
        content_preview=preview,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
