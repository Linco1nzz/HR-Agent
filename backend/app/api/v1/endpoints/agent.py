"""HR Agent 接口：发起任务、SSE 进度流、确认写操作、表单内简历上传。

接口层只做鉴权、参数校验与响应组装；规划、执行、状态机与事件推送位于
``app.services.agent``。``POST /agent/chat`` 立即返回 ``task_id``，不等待 Dify。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile
from fastapi.responses import StreamingResponse
from redis.asyncio.client import PubSub
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.api.v1.responses import sse_response
from app.core.config import settings
from app.core.exceptions import (
    AgentTaskStateError,
    BadRequestError,
    ResumeTooLargeError,
)
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.db.models import Message
from app.db.session import SessionLocal, get_db
from app.schemas.agent import (
    TERMINAL_TASK_STATUSES,
    AgentChatRequest,
    AgentChatResponse,
    AgentConfirmAction,
    AgentConfirmRequest,
    AgentConfirmResponse,
    AgentResumeUploadResponse,
    AgentTaskRead,
    AgentTaskStatus,
)
from app.schemas.conversation import ConversationKind
from app.schemas.error import ErrorResponse
from app.services import conversation_service
from app.services.agent import events, registry, task_service, uploads, worker
from app.services.streaming import encode_sse

logger = get_logger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])

_AUTH_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "缺少令牌、令牌无效或已过期"},
}

_AGENT_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    **_AUTH_ERROR_RESPONSES,
    404: {"model": ErrorResponse, "description": "会话 / 任务 / 上传文件不存在"},
    409: {"model": ErrorResponse, "description": "任务状态不允许该操作"},
    422: {"model": ErrorResponse, "description": "参数不合法"},
}

_TERMINAL_VALUES = {status.value for status in TERMINAL_TASK_STATUSES}


@router.post(
    "/chat",
    response_model=AgentChatResponse,
    status_code=202,
    summary="发起一条 Agent 指令",
    description=(
        "校验会话归属后写入用户消息、创建任务并立即返回 `task_id`；Worker 在后台"
        "规划与执行，进度通过 `GET /agent/stream/{task_id}` 推送。"
    ),
    responses=_AGENT_ERROR_RESPONSES,
)
async def create_agent_task(
    payload: AgentChatRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> AgentChatResponse:
    """创建任务并触发后台 Worker。"""
    conversation = await conversation_service.get_conversation(
        db, payload.conversation_id, user=current_user
    )
    if conversation.kind != ConversationKind.AGENT.value:
        raise BadRequestError(
            "该会话不是 Agent 会话",
            details={"conversation_id": str(conversation.id), "kind": conversation.kind},
        )

    active = await task_service.find_active_task(db, conversation.id)
    if active is not None:
        raise AgentTaskStateError(
            "上一条指令还在执行，请等它结束或先取消",
            details={"task_id": str(active.id), "status": active.status},
        )

    db.add(
        Message(
            conversation_id=conversation.id,
            role="user",
            content=payload.content,
        )
    )
    await db.flush()
    conversation_service.auto_title(conversation, payload.content)
    await conversation_service.update_total_messages(db, conversation.id)
    await db.commit()

    task = await task_service.create_task(
        db,
        conversation_id=conversation.id,
        user_id=current_user.id,
        instruction=payload.content,
    )
    background_tasks.add_task(worker.run_agent, task.id)
    return AgentChatResponse(task_id=task.id, status=AgentTaskStatus(task.status))


@router.get(
    "/stream/{task_id}",
    response_class=StreamingResponse,
    response_model=None,
    summary="订阅任务进度（SSE）",
    description=(
        "先推送数据库中的任务快照（`task_started`），任务未结束则订阅 Redis 事件："
        "`step`、`message`、`confirm_required`、`task_end`。刷新页面后重连不会丢进度。"
    ),
    responses={
        **_AGENT_ERROR_RESPONSES,
        200: {
            "description": "SSE 事件流",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
    },
)
async def stream_task(
    task_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """订阅任务进度；归属校验在建流前完成。"""
    task = await task_service.get_task_for_user(db, task_id, current_user.id)
    fallback_snapshot = worker.task_snapshot(task)
    channel = events.task_channel(task_id)

    async def event_stream() -> AsyncIterator[bytes]:
        # 先读快照：已结束的任务直接回放快照 + task_end，不依赖 Redis。
        async with SessionLocal() as session:
            fresh = await task_service.get_task(session, task_id)
        snapshot = worker.task_snapshot(fresh) if fresh is not None else fallback_snapshot

        pubsub: PubSub | None = None
        if snapshot["status"] not in _TERMINAL_VALUES:
            # 未结束的任务先订阅再重读快照：订阅之后发布的事件不会丢，快照可能已包含
            # 其中一部分，前端按 step_index 幂等合并即可（ADR 0008）。
            try:
                pubsub = get_redis().pubsub()
                await pubsub.subscribe(channel)
            except Exception as exc:  # pragma: no cover - 依赖外部 Redis
                logger.warning(
                    "agent_stream_subscribe_failed", task_id=str(task_id), error=str(exc)
                )
                yield encode_sse(
                    "error",
                    {"status": 503, "code": "SERVICE_UNAVAILABLE", "message": "进度推送暂不可用"},
                )
                return
            async with SessionLocal() as session:
                fresh = await task_service.get_task(session, task_id)
            snapshot = worker.task_snapshot(fresh) if fresh is not None else fallback_snapshot

        try:
            yield encode_sse("task_started", {"task": snapshot})
            if snapshot["status"] in _TERMINAL_VALUES:
                yield encode_sse(
                    "task_end",
                    {
                        "task_id": str(task_id),
                        "status": snapshot["status"],
                        "error": snapshot.get("error_message"),
                    },
                )
                return

            assert pubsub is not None  # 未结束的任务必然已完成订阅
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15.0)
                if message is None:
                    yield events.KEEPALIVE_FRAME
                    continue
                if message.get("type") != "message":
                    continue
                decoded = events.decode_event(message.get("data"))
                if decoded is None:
                    continue
                event, data = decoded
                yield events.encode_event(event, data)
                if event == "task_end":
                    break
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(channel)
                    await pubsub.aclose()
                except Exception:  # pragma: no cover - 关闭失败不影响响应
                    logger.warning("agent_stream_unsubscribe_failed", task_id=str(task_id))

    return sse_response(event_stream())


@router.post(
    "/confirm",
    response_model=AgentConfirmResponse,
    status_code=202,
    summary="确认或取消挂起的写操作",
    description=(
        "`action=confirm` 时可用 `params` 提交修改后的参数（可编辑确认卡片）；"
        "`action=cancel` 放弃当前步骤。Worker 在后台续跑，进度仍走 SSE。"
    ),
    responses=_AGENT_ERROR_RESPONSES,
)
async def confirm_task(
    payload: AgentConfirmRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> AgentConfirmResponse:
    """确认 / 取消一个挂起步骤。"""
    task = await task_service.get_task_for_user(db, payload.task_id, current_user.id)
    if task.status != AgentTaskStatus.WAITING_CONFIRM.value or not task.pending_confirm:
        raise AgentTaskStateError(
            "任务当前没有等待确认的操作",
            details={"task_id": str(payload.task_id), "status": task.status},
        )

    pending = task.pending_confirm
    if payload.action is AgentConfirmAction.CONFIRM and payload.params:
        merged = {**pending.get("args", {}), **payload.params}
        registry.validate_tool_args(str(pending.get("tool")), merged)

    background_tasks.add_task(
        worker.resume_agent,
        task.id,
        payload.action.value,
        payload.params,
    )
    return AgentConfirmResponse(task_id=task.id, status=AgentTaskStatus(task.status))


@router.get(
    "/conversations/{conversation_id}/active-task",
    response_model=AgentTaskRead | None,
    summary="获取会话中未结束的任务",
    description=(
        "刷新页面后用于恢复进度与确认卡片：返回该会话最近一个未结束的任务，" "没有时返回 null。"
    ),
    responses=_AGENT_ERROR_RESPONSES,
)
async def read_active_task(
    conversation_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> AgentTaskRead | None:
    """返回会话中最近一个未结束的任务。"""
    conversation = await conversation_service.get_conversation(
        db, conversation_id, user=current_user
    )
    task = await task_service.find_active_task(db, conversation.id)
    if task is None:
        return None
    return AgentTaskRead.model_validate(task)


@router.get(
    "/tasks/{task_id}",
    response_model=AgentTaskRead,
    summary="获取任务快照",
    description="用于刷新页面后恢复步骤时间线与确认卡片；不存在或非本人任务返回 404。",
    responses=_AGENT_ERROR_RESPONSES,
)
async def read_task(
    task_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> AgentTaskRead:
    """读取任务快照。"""
    task = await task_service.get_task_for_user(db, task_id, current_user.id)
    return AgentTaskRead.model_validate(task)


@router.post(
    "/uploads/resume",
    response_model=AgentResumeUploadResponse,
    status_code=201,
    summary="确认表单内上传简历（只解析，不评分）",
    description=(
        "上传 PDF / DOC / DOCX / TXT 简历，后端保存文件并解析文本，返回 `upload_id`；"
        "把它作为 `score_resume` 的 `upload_id` 参数提交即可在确认后评分。"
    ),
    responses={
        **_AGENT_ERROR_RESPONSES,
        413: {"model": ErrorResponse, "description": "简历文件超过大小限制"},
    },
)
async def upload_resume(
    _current_user: CurrentUser,
    file: UploadFile = File(..., description="简历文件（PDF / DOC / DOCX / TXT）"),
) -> AgentResumeUploadResponse:
    """保存并解析上传的简历。"""
    max_bytes = settings.resume_max_file_size_mb * 1024 * 1024
    if file.size is not None and file.size > max_bytes:
        raise ResumeTooLargeError(
            f"简历文件不能超过 {settings.resume_max_file_size_mb}MB",
            details={"max_size_mb": settings.resume_max_file_size_mb, "file_size": file.size},
        )
    content = await file.read()
    return await uploads.save_upload(file.filename or "", content)
