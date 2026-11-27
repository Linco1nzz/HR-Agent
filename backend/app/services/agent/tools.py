"""工具执行器：把注册表里的 8 个原子工具接到现有业务 service 上。

原则（SPEC 第 0 节）：不重写 Dify 调用与业务逻辑，只做参数适配与结果整形；
生成类工具复用各 service 的流式生成，写工具复用各 service 的创建 / 更新 /
归档函数。每个工具执行时自建 ``AsyncSession``，与任务状态库写入互不阻塞。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar
from uuid import UUID

import httpx
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AgentToolFailedError, AgentToolValidationError
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.schemas.interview_plan import (
    GenerateInterviewPlanRequest,
    InterviewPlanCreate,
    InterviewPlanUpdate,
)
from app.schemas.jd import GenerateJDRequest, JobDescriptionCreate, JobDescriptionUpdate
from app.schemas.scoring_criteria import (
    GenerateScoringCriteriaRequest,
    ScoringCriteriaCreate,
    ScoringCriteriaUpdate,
)
from app.services import (
    dify_service,
    interview_plan_service,
    jd_service,
    resume_evaluation_service,
    scoring_criteria_service,
)
from app.services.agent import registry, uploads

logger = get_logger(__name__)

#: 生成增量文本的回调（Worker 用它推送 ``message`` 事件）
DeltaCallback = Callable[[str], Awaitable[None]]

#: 参数模型实例的类型变量
ParamsT = TypeVar("ParamsT", bound=BaseModel)

#: 资源类型的中文名
RESOURCE_LABELS: dict[str, str] = {
    "jd": "JD",
    "scoring_criteria": "评分标准",
    "interview_plan": "面试方案",
    "resume_evaluation": "简历记录",
}


@dataclass(slots=True)
class ToolResult:
    """工具执行结果。

    ``save_payload`` 非空表示该生成结果可落库：Worker 会在步骤完成后追加一个
    ``save_resource`` 确认步骤（ADR 0004 / 0007）。
    """

    content: str = ""
    preview: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    save_payload: dict[str, Any] | None = None
    persisted: bool = False


async def execute_tool(
    name: str,
    args: dict[str, Any],
    *,
    user_id: UUID,
    client: httpx.AsyncClient | None = None,
    on_delta: DeltaCallback | None = None,
) -> ToolResult:
    """校验参数并执行工具；执行在独立数据库会话中完成。"""
    params = registry.validate_tool_args(name, args)
    handler = _HANDLERS[name]
    async with SessionLocal() as db:
        return await handler(db, params, user_id=user_id, client=client, on_delta=on_delta)


# ---------------------------------------------------------------------------
# SSE 生成流消费
# ---------------------------------------------------------------------------
def _parse_frame(frame: bytes) -> tuple[str | None, dict[str, Any]]:
    """解析一帧 ``event:`` + ``data:`` SSE。"""
    event: str | None = None
    data_lines: list[str] = []
    for line in frame.split(b"\n"):
        if line.startswith(b"event:"):
            event = line[6:].strip().decode("utf-8", errors="replace") or None
        elif line.startswith(b"data:"):
            data_lines.append(line[5:].lstrip().decode("utf-8", errors="replace"))
    if not data_lines:
        return event, {}
    try:
        payload = json.loads("\n".join(data_lines))
    except ValueError:
        return event, {}
    return event, payload if isinstance(payload, dict) else {}


async def consume_generation(
    stream: AsyncIterator[bytes],
    on_delta: DeltaCallback | None,
) -> tuple[str, dict[str, Any]]:
    """消费 ``stream_chatflow`` 的 SSE 帧：转发增量、返回 done 载荷。"""
    buffer = b""
    done: dict[str, Any] = {}
    async for chunk in stream:
        if not chunk:
            continue
        buffer += chunk.replace(b"\r\n", b"\n")
        while True:
            boundary = buffer.find(b"\n\n")
            if boundary < 0:
                break
            frame, buffer = buffer[:boundary], buffer[boundary + 2 :]
            event, data = _parse_frame(frame)
            if event == "delta":
                text = data.get("content")
                if isinstance(text, str) and text and on_delta is not None:
                    await on_delta(text)
            elif event == "done":
                done = data
            elif event == "error":
                raise AgentToolFailedError(
                    str(data.get("message") or "生成失败，请稍后重试"),
                    details={
                        "code": data.get("code"),
                        "status": data.get("status"),
                    },
                )
    content = done.get("content")
    if not isinstance(content, str) or not content.strip():
        raise AgentToolFailedError("生成结果为空，请稍后重试")
    return content, done


# ---------------------------------------------------------------------------
# 生成类工具
# ---------------------------------------------------------------------------
async def _generate_jd(
    db: AsyncSession,  # noqa: ARG001 - 统一 handler 签名
    params: BaseModel,
    *,
    user_id: UUID,
    client: httpx.AsyncClient | None,
    on_delta: DeltaCallback | None,
) -> ToolResult:
    """生成 JD（不落库，结果可保存）。"""
    assert isinstance(params, registry.GenerateJdParams)
    request = GenerateJDRequest(
        title=params.title,
        department=params.department,
        location=params.location,
        salary_range=params.salary_range,
        experience_level=params.experience_level,
        education=params.education,
        job_type=params.job_type,
        skills=params.skills,
        requirements=params.requirements,
    )
    content, _ = await consume_generation(
        jd_service.stream_generate_jd(request, user_id=user_id, client=client),
        on_delta,
    )
    preview = jd_service.strip_markdown(content)[:200]
    save_data = {
        "title": params.title,
        "department": params.department,
        "location": params.location,
        "salary_range": params.salary_range,
        "experience_level": params.experience_level,
        "education": params.education,
        "job_type": params.job_type,
        "skills": params.skills,
        "requirements": params.requirements,
        "content": content,
        "status": "generated",
    }
    return ToolResult(
        content=content,
        preview=preview,
        data={"title": params.title, "content_chars": len(content)},
        save_payload={"resource": "jd", "data": save_data},
    )


async def _generate_criteria(
    db: AsyncSession,
    params: BaseModel,
    *,
    user_id: UUID,
    client: httpx.AsyncClient | None,
    on_delta: DeltaCallback | None,
) -> ToolResult:
    """生成简历评分标准（不落库，结果可保存）。"""
    assert isinstance(params, registry.GenerateCriteriaParams)
    stream = await scoring_criteria_service.stream_generate_scoring_criteria(
        db,
        GenerateScoringCriteriaRequest(
            job_description_id=params.job_description_id,
            title=params.title,
            total_score=params.total_score,
            instructions=params.instructions,
        ),
        user_id=user_id,
        client=client,
    )
    content, done = await consume_generation(stream, on_delta)
    preview = jd_service.strip_markdown(content)[:200]
    save_data = {
        "title": done.get("title") or params.title,
        "job_title": done.get("job_title"),
        "content": content,
        "total_score": done.get("total_score") or params.total_score,
        "job_description_id": str(params.job_description_id),
        "status": "generated",
    }
    return ToolResult(
        content=content,
        preview=preview,
        data={"title": save_data["title"], "content_chars": len(content)},
        save_payload={"resource": "scoring_criteria", "data": save_data},
    )


async def _generate_interview(
    db: AsyncSession,
    params: BaseModel,
    *,
    user_id: UUID,
    client: httpx.AsyncClient | None,
    on_delta: DeltaCallback | None,
) -> ToolResult:
    """生成面试方案（不落库，结果可保存）。"""
    assert isinstance(params, registry.GenerateInterviewParams)
    stream = await interview_plan_service.stream_generate_interview_plan(
        db,
        GenerateInterviewPlanRequest(
            resume_evaluation_id=params.resume_evaluation_id,
            instructions=params.instructions,
        ),
        user_id=user_id,
        client=client,
    )
    content, done = await consume_generation(stream, on_delta)
    preview = jd_service.strip_markdown(content)[:200]
    save_data = {
        "candidate_name": done.get("candidate_name") or "候选人",
        "candidate_position": done.get("candidate_position") or "未指定岗位",
        "content": content,
        "resume_evaluation_id": str(params.resume_evaluation_id),
    }
    return ToolResult(
        content=content,
        preview=preview,
        data={
            "candidate_name": save_data["candidate_name"],
            "candidate_position": save_data["candidate_position"],
            "content_chars": len(content),
        },
        save_payload={"resource": "interview_plan", "data": save_data},
    )


async def _score_resume(
    db: AsyncSession,
    params: BaseModel,
    *,
    user_id: UUID,
    client: httpx.AsyncClient | None,
    on_delta: DeltaCallback | None,  # noqa: ARG001 - 评分无流式文本
) -> ToolResult:
    """对已有简历重评或对表单内上传的简历评分并落库。"""
    assert isinstance(params, registry.ScoreResumeParams)
    http = client or dify_service.get_client()
    if params.resume_evaluation_id is not None:
        record = await resume_evaluation_service.rescore_resume(
            db,
            evaluation_id=params.resume_evaluation_id,
            job_description_id=params.job_description_id,
            user_id=user_id,
            client=http,
        )
        candidate = record.candidate_name or record.original_filename
    else:
        upload_id = params.upload_id or ""
        filename, content = await uploads.load_upload(upload_id)
        record = await resume_evaluation_service.evaluate_resume(
            db,
            filename=filename,
            content=content,
            job_description_id=params.job_description_id,
            user_id=user_id,
            client=http,
        )
        uploads.cleanup_upload(upload_id)
        candidate = record.candidate_name or record.original_filename

    score = record.total_score
    max_score = record.max_score
    summary = f"{candidate} 的简历评分：{score if score is not None else '—'} / {max_score or '—'}"
    return ToolResult(
        content=summary,
        preview=summary,
        data={
            "resume_evaluation_id": str(record.id),
            "candidate_name": record.candidate_name,
            "total_score": record.total_score,
            "max_score": record.max_score,
        },
        persisted=True,
    )


# ---------------------------------------------------------------------------
# 查询 / 写工具
# ---------------------------------------------------------------------------
async def _query_resource(
    db: AsyncSession,
    params: BaseModel,
    *,
    user_id: UUID,  # noqa: ARG001 - 统一 handler 签名
    client: httpx.AsyncClient | None,  # noqa: ARG001 - 统一 handler 签名
    on_delta: DeltaCallback | None,  # noqa: ARG001 - 查询无流式文本
) -> ToolResult:
    """只读查询业务资源，返回可读列表与结构化 items。"""
    assert isinstance(params, registry.QueryResourceParams)
    items: list[dict[str, Any]]
    total: int
    if params.resource == "jd":
        records, total = await jd_service.list_jds(
            db, page=1, page_size=params.limit, keyword=params.keyword
        )
        items = [
            {"id": str(record.id), "title": record.title, "status": record.status}
            for record in records
        ]
    elif params.resource == "scoring_criteria":
        criteria, total = await scoring_criteria_service.list_scoring_criteria(
            db, page=1, page_size=params.limit, keyword=params.keyword
        )
        items = [
            {
                "id": str(record.id),
                "title": record.title,
                "job_title": record.job_title,
                "status": record.status,
            }
            for record in criteria
        ]
    elif params.resource == "resume_evaluation":
        evaluations, total = await resume_evaluation_service.list_resume_evaluations(
            db, page=1, page_size=params.limit, keyword=params.keyword
        )
        items = [
            {
                "id": str(record.id),
                "name": record.candidate_name or record.original_filename,
                "job_title": record.job_title,
                "total_score": record.total_score,
            }
            for record in evaluations
        ]
    else:
        plans, total = await interview_plan_service.list_interview_plans(
            db, page=1, page_size=params.limit, keyword=params.keyword
        )
        items = [
            {
                "id": str(record.id),
                "candidate_name": record.candidate_name,
                "job_title": record.job_title,
            }
            for record in plans
        ]

    label = RESOURCE_LABELS.get(params.resource, params.resource)
    if not items:
        content = f"没有查询到符合条件的{label}。"
    else:
        lines = [f"共 {total} 条{label}，展示前 {len(items)} 条："]
        for item in items:
            title = item.get("title") or item.get("name") or item.get("candidate_name") or ""
            lines.append(f"- {item['id']}  {title}")
        content = "\n".join(lines)
    return ToolResult(
        content=content,
        preview=content.splitlines()[0][:200],
        data={"resource": params.resource, "items": items, "total": total},
    )


def _validate_data(schema: type[ParamsT], data: dict[str, Any], label: str) -> ParamsT:
    """用对应的创建 / 更新 schema 校验落库字段。"""
    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        raise AgentToolValidationError(
            f"{label}字段不合法",
            details={
                "errors": [
                    {"field": ".".join(str(part) for part in error["loc"]), "message": error["msg"]}
                    for error in exc.errors()
                ]
            },
        ) from exc


async def _save_resource(
    db: AsyncSession,
    params: BaseModel,
    *,
    user_id: UUID,
    client: httpx.AsyncClient | None,  # noqa: ARG001 - 统一 handler 签名
    on_delta: DeltaCallback | None,  # noqa: ARG001 - 保存无流式文本
) -> ToolResult:
    """把生成结果落库为 JD / 评分标准 / 面试方案。"""
    assert isinstance(params, registry.SaveResourceParams)
    label = RESOURCE_LABELS[params.resource]
    if params.resource == "jd":
        jd_payload = _validate_data(JobDescriptionCreate, params.data, label)
        jd = await jd_service.create_jd(db, jd_payload, user_id=user_id)
        resource_id, title = jd.id, jd.title
    elif params.resource == "scoring_criteria":
        criteria_payload = _validate_data(ScoringCriteriaCreate, params.data, label)
        criteria = await scoring_criteria_service.create_scoring_criteria(
            db, criteria_payload, user_id=user_id
        )
        resource_id, title = criteria.id, criteria.title
    else:
        plan_payload = _validate_data(InterviewPlanCreate, params.data, label)
        plan = await interview_plan_service.create_interview_plan(db, plan_payload, user_id=user_id)
        resource_id, title = plan.id, plan.candidate_name

    summary = f"已保存{label}：{title}（{resource_id}）"
    return ToolResult(
        content=summary,
        preview=summary,
        data={"resource": params.resource, "id": str(resource_id), "title": title},
        persisted=True,
    )


async def _edit_resource(
    db: AsyncSession,
    params: BaseModel,
    *,
    user_id: UUID,
    client: httpx.AsyncClient | None,  # noqa: ARG001 - 统一 handler 签名
    on_delta: DeltaCallback | None,  # noqa: ARG001 - 编辑无流式文本
) -> ToolResult:
    """编辑已保存的 JD / 评分标准 / 面试方案。"""
    assert isinstance(params, registry.EditResourceParams)
    label = RESOURCE_LABELS[params.resource]
    if params.resource == "jd":
        jd_update = _validate_data(JobDescriptionUpdate, params.data, label)
        jd = await jd_service.update_jd(db, params.resource_id, jd_update, user_id=user_id)
        title = jd.title
    elif params.resource == "scoring_criteria":
        criteria_update = _validate_data(ScoringCriteriaUpdate, params.data, label)
        criteria = await scoring_criteria_service.update_scoring_criteria(
            db, params.resource_id, criteria_update, user_id=user_id
        )
        title = criteria.title
    else:
        plan_update = _validate_data(InterviewPlanUpdate, params.data, label)
        plan = await interview_plan_service.update_interview_plan(
            db, params.resource_id, plan_update, user_id=user_id
        )
        title = plan.candidate_name

    summary = f"已更新{label}：{title}"
    return ToolResult(
        content=summary,
        preview=summary,
        data={"resource": params.resource, "id": str(params.resource_id), "title": title},
        persisted=True,
    )


async def _delete_resource(
    db: AsyncSession,
    params: BaseModel,
    *,
    user_id: UUID,
    client: httpx.AsyncClient | None,  # noqa: ARG001 - 统一 handler 签名
    on_delta: DeltaCallback | None,  # noqa: ARG001 - 删除无流式文本
) -> ToolResult:
    """软删除已保存资源（归档，不物理删除）。"""
    assert isinstance(params, registry.DeleteResourceParams)
    label = RESOURCE_LABELS[params.resource]
    if params.resource == "jd":
        await jd_service.archive_jd(db, params.resource_id, user_id=user_id)
    elif params.resource == "scoring_criteria":
        await scoring_criteria_service.archive_scoring_criteria(
            db, params.resource_id, user_id=user_id
        )
    else:
        await interview_plan_service.archive_interview_plan(db, params.resource_id, user_id=user_id)
    summary = f"已删除{label}（{params.resource_id}）"
    return ToolResult(
        content=summary,
        preview=summary,
        data={"resource": params.resource, "id": str(params.resource_id)},
        persisted=True,
    )


#: 工具名 → 执行函数
_HANDLERS: dict[str, Callable[..., Awaitable[ToolResult]]] = {
    "generate_jd": _generate_jd,
    "generate_criteria": _generate_criteria,
    "generate_interview": _generate_interview,
    "score_resume": _score_resume,
    "query_resource": _query_resource,
    "save_resource": _save_resource,
    "edit_resource": _edit_resource,
    "delete_resource": _delete_resource,
}


def describe_args(tool: str, args: dict[str, Any]) -> str:
    """生成确认卡片的一句话摘要（写进 ``pending_confirm.summary``）。"""
    resource = args.get("resource")
    label = RESOURCE_LABELS.get(str(resource), str(resource or "资源"))
    if tool == "generate_jd":
        return f"即将生成 JD：{args.get('title', '')}"
    if tool == "generate_criteria":
        return f"即将为 JD {args.get('job_description_id', '')} 生成评分标准"
    if tool == "generate_interview":
        return f"即将为简历 {args.get('resume_evaluation_id', '')} 生成面试方案"
    if tool == "score_resume":
        target = args.get("resume_evaluation_id") or args.get("upload_id")
        return f"即将按 JD {args.get('job_description_id', '')} 对简历 {target} 评分"
    if tool == "save_resource":
        return f"即将保存{label}"
    if tool == "edit_resource":
        return f"即将编辑{label}：{args.get('resource_id', '')}"
    if tool == "delete_resource":
        return f"即将删除{label}：{args.get('resource_id', '')}（软删除）"
    return f"即将执行 {tool}"


__all__ = [
    "DeltaCallback",
    "ToolResult",
    "consume_generation",
    "describe_args",
    "execute_tool",
]
