"""Agent Worker：脱离 HTTP 上下文执行任务。

执行模型（ADR 0004 / 0007 / 0008）：

1. Planner 给出步骤计划，立即落库并推送 ``task_started``；
2. 逐步执行：免确认工具直接执行（生成类同时推送 ``message`` 增量）；
3. 需要确认的步骤（生成前参数表单 / 落库 / 编辑 / 删除）挂起任务、推送
   ``confirm_required`` 后 Worker 直接返回，绝不阻塞；
4. ``POST /agent/confirm`` 触发 ``resume_agent`` 继续执行剩余步骤；
5. 任务终态写一条助手汇总消息并推送 ``task_end``。

Worker 的所有数据库读写都通过独立 ``AsyncSession``，不依赖请求级会话。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AgentTaskStateError, AgentToolValidationError, AppException
from app.core.logging import get_logger
from app.db.models import AgentTask, Message
from app.db.session import SessionLocal
from app.schemas.agent import (
    AgentConfirmAction,
    AgentStepStatus,
    AgentTaskRead,
    AgentTaskStatus,
)
from app.services import conversation_service
from app.services.agent import events, planner, registry, task_service, tools

logger = get_logger(__name__)

#: 步骤预览截断长度
_PREVIEW_CHARS = 200


# ---------------------------------------------------------------------------
# 快照与事件
# ---------------------------------------------------------------------------
def task_snapshot(task: AgentTask) -> dict[str, Any]:
    """把任务序列化成前端契约（与 ``GET /agent/tasks/{id}`` 一致）。"""
    return AgentTaskRead.model_validate(task).model_dump(mode="json")


def _new_step(index: int, tool: str, args: dict[str, Any], summary: str) -> dict[str, Any]:
    """构造一个等待中的步骤快照。"""
    spec = registry.get_tool(tool)
    return {
        "step_index": index,
        "tool": tool,
        "name": spec.name_cn,
        "status": AgentStepStatus.PENDING.value,
        "args": args,
        "summary": summary,
        "result_preview": None,
        "content": None,
        "error": None,
        "editable": spec.editable,
    }


async def _set_step(
    db: AsyncSession,
    task: AgentTask,
    index: int,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """更新单个步骤并落库 + 推送 ``step`` 事件。"""
    steps = list(task.steps)
    steps[index] = {**steps[index], **updates}
    await task_service.set_steps(db, task, steps)
    await events.publish_event(task.id, "step", {"step": steps[index]})
    return steps[index]


# ---------------------------------------------------------------------------
# 入口：创建后启动 / 确认后恢复
# ---------------------------------------------------------------------------
async def run_agent(task_id: UUID) -> None:
    """任务入口：规划 → 公布计划 → 逐步执行。"""
    try:
        await _run_agent(task_id)
    except Exception:  # pragma: no cover - 兜底，避免后台任务异常吞掉状态
        logger.exception("agent_worker_crashed", task_id=str(task_id))
        await _mark_failed(task_id, "任务执行异常，请稍后重试")


async def _run_agent(task_id: UUID) -> None:
    async with SessionLocal() as db:
        task = await task_service.get_task(db, task_id)
        if task is None:
            logger.warning("agent_task_missing", task_id=str(task_id))
            return
        if task.status != AgentTaskStatus.CREATED.value:
            logger.info("agent_task_skipped", task_id=str(task_id), status=task.status)
            return

        plan = await planner.plan(task.instruction)
        if not plan.steps:
            await _finish_with_message(
                db,
                task,
                plan.reply or planner.FALLBACK_REPLY,
                status=AgentTaskStatus.COMPLETED,
            )
            return

        steps = [
            _new_step(index, step.tool, step.args, step.summary)
            for index, step in enumerate(plan.steps)
        ]
        await task_service.set_steps(db, task, steps)
        await task_service.set_status(db, task, AgentTaskStatus.RUNNING)
        await events.publish_event(task.id, "task_started", {"task": task_snapshot(task)})
        await _advance(db, task, 0)


async def resume_agent(task_id: UUID, action: str, params: dict[str, Any] | None) -> None:
    """确认 / 取消挂起步骤后继续执行。"""
    try:
        await _resume_agent(task_id, action, params)
    except Exception:  # pragma: no cover - 兜底
        logger.exception("agent_resume_crashed", task_id=str(task_id))
        await _mark_failed(task_id, "任务恢复失败，请重新发起")


async def _resume_agent(task_id: UUID, action: str, params: dict[str, Any] | None) -> None:
    async with SessionLocal() as db:
        task = await task_service.get_task(db, task_id)
        if task is None:
            logger.warning("agent_task_missing", task_id=str(task_id))
            return
        if task.status != AgentTaskStatus.WAITING_CONFIRM.value or not task.pending_confirm:
            raise AgentTaskStateError(
                "任务当前不处于等待确认状态",
                details={"task_id": str(task_id), "status": task.status},
            )

        pending = task.pending_confirm
        index = int(pending["step_index"])
        step = task.steps[index]

        if action == AgentConfirmAction.CANCEL.value:
            await _set_step(
                db,
                task,
                index,
                {"status": AgentStepStatus.CANCELLED.value, "error": "用户取消"},
            )
            await _finish(db, task, AgentTaskStatus.CANCELLED)
            return

        # 确认：合并用户修改后的参数并重新校验
        merged_args = {**step.get("args", {}), **(params or {})}
        registry.validate_tool_args(step["tool"], merged_args)
        await task_service.set_pending_confirm(db, task, None)
        await task_service.set_status(db, task, AgentTaskStatus.RUNNING)
        await _set_step(
            db,
            task,
            index,
            {"status": AgentStepStatus.RUNNING.value, "args": merged_args},
        )
        ok = await _run_step(db, task, index)
        if not ok:
            return
        await _advance(db, task, index + 1)


# ---------------------------------------------------------------------------
# 执行循环
# ---------------------------------------------------------------------------
async def _advance(db: Any, task: AgentTask, index: int) -> None:
    """从 ``index`` 开始执行，遇到需确认步骤挂起，全部完成则结束任务。"""
    while index < len(task.steps):
        await task_service.set_current_step_index(db, task, index)
        step = task.steps[index]
        spec = registry.get_tool(step["tool"])

        if spec.require_confirm:
            await _suspend(db, task, index, step, spec.name_cn, spec.editable)
            return

        await _set_step(
            db,
            task,
            index,
            {"status": AgentStepStatus.RUNNING.value},
        )
        ok = await _run_step(db, task, index)
        if not ok:
            return
        index += 1

    await _finish(db, task, AgentTaskStatus.COMPLETED)


async def _run_step(db: Any, task: AgentTask, index: int) -> bool:
    """执行一个已标记为 running 的步骤；失败时结束整个任务。"""
    step = task.steps[index]

    async def on_delta(text: str) -> None:
        await events.publish_event(
            task.id,
            "message",
            {"text": text, "step_index": index},
        )

    try:
        result = await tools.execute_tool(
            step["tool"],
            step["args"],
            user_id=task.user_id,
            client=None,
            on_delta=on_delta,
        )
    except AgentToolValidationError as exc:
        await _fail_step(db, task, index, exc.message)
        return False
    except AppException as exc:
        await _fail_step(db, task, index, exc.message)
        return False
    except Exception:
        logger.exception(
            "agent_tool_crashed",
            task_id=str(task.id),
            step_index=index,
            tool=step["tool"],
        )
        await _fail_step(db, task, index, "操作执行失败，请稍后重试")
        return False

    content = result.content.strip()
    preview = (result.preview or content)[:_PREVIEW_CHARS]
    await _set_step(
        db,
        task,
        index,
        {
            "status": AgentStepStatus.COMPLETED.value,
            "result_preview": preview,
            "content": content or None,
            "error": None,
        },
    )

    # 生成类结果需要用户确认后才落库（ADR 0004 / 0007）
    if result.save_payload is not None:
        steps = list(task.steps)
        save_summary = tools.describe_args("save_resource", result.save_payload)
        save_step = _new_step(len(steps), "save_resource", result.save_payload, save_summary)
        steps.append(save_step)
        await task_service.set_steps(db, task, steps)
        await events.publish_event(task.id, "step", {"step": save_step})
    return True


async def _suspend(
    db: AsyncSession,
    task: AgentTask,
    index: int,
    step: dict[str, Any],
    name_cn: str,
    editable: bool,
) -> None:
    """挂起任务等待用户确认：落库后推送事件并让 Worker 退出。"""
    await _set_step(
        db,
        task,
        index,
        {"status": AgentStepStatus.WAITING_CONFIRM.value},
    )
    pending = {
        "step_index": index,
        "tool": step["tool"],
        "name": name_cn,
        "summary": tools.describe_args(step["tool"], step.get("args", {})),
        "args": step.get("args", {}),
        "editable": editable,
    }
    await task_service.set_pending_confirm(db, task, pending)
    await task_service.set_status(db, task, AgentTaskStatus.WAITING_CONFIRM)
    await events.publish_event(
        task.id,
        "confirm_required",
        {"task_id": str(task.id), "pending_confirm": pending},
    )


async def _fail_step(db: Any, task: AgentTask, index: int, message: str) -> None:
    """标记步骤失败并结束任务。"""
    await _set_step(
        db,
        task,
        index,
        {"status": AgentStepStatus.FAILED.value, "error": message},
    )
    await _finish(db, task, AgentTaskStatus.FAILED, error=message)


# ---------------------------------------------------------------------------
# 结束与消息落库
# ---------------------------------------------------------------------------
async def _finish(
    db: AsyncSession,
    task: AgentTask,
    status: AgentTaskStatus,
    *,
    error: str | None = None,
) -> None:
    """写终态、落助手汇总消息并推送 ``task_end``。"""
    await task_service.set_pending_confirm(db, task, None)
    await task_service.set_status(db, task, status, error_message=error)
    await _write_assistant_message(db, task, status, error=error)
    await events.publish_event(
        task.id,
        "task_end",
        {"task_id": str(task.id), "status": status.value, "error": error},
    )


async def _finish_with_message(
    db: AsyncSession,
    task: AgentTask,
    content: str,
    *,
    status: AgentTaskStatus,
) -> None:
    """没有可执行步骤时，直接把回复作为助手消息返回。"""
    await task_service.set_status(db, task, status)
    await _write_assistant_message(db, task, status, content_override=content)
    await events.publish_event(
        task.id,
        "task_end",
        {"task_id": str(task.id), "status": status.value, "error": None},
    )


def _assistant_content(task: AgentTask, status: AgentTaskStatus, error: str | None) -> str:
    """根据步骤结果拼装助手汇总消息。"""
    if status == AgentTaskStatus.FAILED:
        return error or "任务执行失败，请稍后重试。"
    if status == AgentTaskStatus.CANCELLED:
        return "任务已取消。"

    parts: list[str] = []
    for step in task.steps or []:
        if step.get("status") != AgentStepStatus.COMPLETED.value:
            continue
        content = step.get("content")
        summary = step.get("result_preview") or step.get("summary")
        if isinstance(content, str) and content.strip():
            parts.append(content.strip())
        elif isinstance(summary, str) and summary.strip():
            parts.append(summary.strip())
    return "\n\n".join(parts) if parts else "任务已完成。"


async def _write_assistant_message(
    db: AsyncSession,
    task: AgentTask,
    status: AgentTaskStatus,
    *,
    error: str | None = None,
    content_override: str | None = None,
) -> None:
    """把助手汇总写入 ``messages`` 并刷新会话统计。"""
    content = content_override or _assistant_content(task, status, error)
    record = Message(
        conversation_id=task.conversation_id,
        role="assistant",
        content=content,
        meta_data={
            "task_id": str(task.id),
            "status": status.value,
            "steps": [
                {
                    "tool": step.get("tool"),
                    "name": step.get("name"),
                    "status": step.get("status"),
                }
                for step in task.steps or []
            ],
        },
    )
    db.add(record)
    await db.flush()
    await conversation_service.update_total_messages(db, task.conversation_id)
    await db.commit()
    logger.info(
        "agent_assistant_message_saved",
        task_id=str(task.id),
        conversation_id=str(task.conversation_id),
        status=status.value,
        content_chars=len(content),
    )


async def _mark_failed(task_id: UUID, message: str) -> None:
    """兜底：把任务标记为失败，避免状态停在 running。"""
    try:
        async with SessionLocal() as db:
            task = await task_service.get_task(db, task_id)
            if task is None or task.status in task_service.TERMINAL_STATUSES:
                return
            await _finish(db, task, AgentTaskStatus.FAILED, error=message)
    except Exception:  # pragma: no cover - 兜底失败只能记日志
        logger.exception("agent_mark_failed_failed", task_id=str(task_id))
