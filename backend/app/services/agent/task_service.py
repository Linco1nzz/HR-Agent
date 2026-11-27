"""Agent 任务持久化与状态机。

任务的所有读写都走这里：Worker 脱离 HTTP 上下文，用独立 ``AsyncSession`` 调用；
状态变更立即提交，保证 SSE 重连时读到的快照与推送一致。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AgentTaskNotFoundError
from app.core.logging import get_logger
from app.db.models import AgentTask
from app.db.session import SessionLocal
from app.schemas.agent import AgentTaskStatus

logger = get_logger(__name__)

#: 任务终态：进入后不再执行、不再接受确认
TERMINAL_STATUSES: frozenset[str] = frozenset(
    {
        AgentTaskStatus.COMPLETED.value,
        AgentTaskStatus.FAILED.value,
        AgentTaskStatus.CANCELLED.value,
    }
)

#: 应用重启时需要收尾的中间态
STALLED_STATUSES: tuple[str, ...] = (
    AgentTaskStatus.RUNNING.value,
    AgentTaskStatus.WAITING_CONFIRM.value,
)

RESTART_FAILURE_REASON = "服务重启，任务已中断，请重新发起"


def _now() -> datetime:
    """统一使用 UTC 时间。"""
    return datetime.now(UTC)


async def create_task(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    user_id: UUID,
    instruction: str,
) -> AgentTask:
    """创建任务并立即提交，供 BackgroundTasks 取到稳定的 task_id。"""
    record = AgentTask(
        conversation_id=conversation_id,
        user_id=user_id,
        instruction=instruction,
        status=AgentTaskStatus.CREATED.value,
        current_step_index=0,
        steps=[],
        pending_confirm=None,
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    logger.info(
        "agent_task_created",
        task_id=str(record.id),
        conversation_id=str(conversation_id),
        user_id=str(user_id),
    )
    return record


async def get_task(db: AsyncSession, task_id: UUID) -> AgentTask | None:
    """按 ID 取任务（Worker 使用，不做归属过滤）。"""
    return await db.get(AgentTask, task_id)


async def get_task_for_user(db: AsyncSession, task_id: UUID, user_id: UUID) -> AgentTask:
    """按 ID 取当前用户的任务；不存在或不属于该用户时抛 404。"""
    record = await db.get(AgentTask, task_id)
    if record is None or not record.is_active or record.user_id != user_id:
        raise AgentTaskNotFoundError(details={"task_id": str(task_id)})
    return record


async def set_status(
    db: AsyncSession,
    task: AgentTask,
    status: AgentTaskStatus,
    *,
    error_message: str | None = None,
) -> AgentTask:
    """更新任务状态并提交。"""
    task.status = status.value
    task.error_message = error_message
    task.updated_at = _now()
    await db.commit()
    await db.refresh(task)
    logger.info(
        "agent_task_status",
        task_id=str(task.id),
        status=task.status,
        error_message=error_message,
    )
    return task


async def set_steps(db: AsyncSession, task: AgentTask, steps: list[dict[str, Any]]) -> None:
    """整体替换步骤快照并提交（JSONB 需要重新赋值才能被脏检查发现）。"""
    task.steps = steps
    task.updated_at = _now()
    await db.commit()
    await db.refresh(task)


async def set_pending_confirm(
    db: AsyncSession,
    task: AgentTask,
    payload: dict[str, Any] | None,
) -> None:
    """写入 / 清空待确认动作并提交。"""
    task.pending_confirm = payload
    task.updated_at = _now()
    await db.commit()
    await db.refresh(task)


async def set_current_step_index(db: AsyncSession, task: AgentTask, index: int) -> None:
    """记录当前执行到的步骤下标并提交。"""
    task.current_step_index = index
    task.updated_at = _now()
    await db.commit()
    await db.refresh(task)


async def mark_stalled_tasks_failed(reason: str = RESTART_FAILURE_REASON) -> int:
    """应用启动时把中断的任务标记为失败（ADR 0005：不做重启续跑）。"""
    async with SessionLocal() as db:
        result = await db.execute(
            update(AgentTask)
            .where(AgentTask.status.in_(STALLED_STATUSES))
            .values(
                status=AgentTaskStatus.FAILED.value,
                error_message=reason,
                pending_confirm=None,
                updated_at=_now(),
            )
        )
        await db.commit()
        count = int(getattr(result, "rowcount", 0) or 0)
    if count:
        logger.warning("agent_tasks_marked_failed_on_startup", count=count, reason=reason)
    return count


async def find_active_task(db: AsyncSession, conversation_id: UUID) -> AgentTask | None:
    """返回会话中最近一个未结束的任务（用于避免并发指令互相覆盖）。"""
    stmt = (
        select(AgentTask)
        .where(
            AgentTask.conversation_id == conversation_id,
            AgentTask.is_active.is_(True),
            AgentTask.status.not_in(tuple(TERMINAL_STATUSES)),
        )
        .order_by(AgentTask.created_at.desc())
        .limit(1)
    )
    return await db.scalar(stmt)
