"""Worker 状态机单元测试：确认挂起、保存闭环与恢复（不依赖数据库 / Redis / LLM）。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from app.core.exceptions import AgentToolFailedError
from app.db.models import AgentTask, Conversation
from app.schemas.agent import AgentStepStatus, AgentTaskStatus
from app.services.agent import events, tools, worker


class FakeSession:
    """覆盖 Worker 写任务状态与落助手消息所需的 AsyncSession 子集。"""

    def __init__(self, task: AgentTask | None = None) -> None:
        self.task = task
        self.added: list[Any] = []
        self.commits = 0
        self.scalar_value: Any = 0

    async def get(self, model: type, pk: Any) -> Any:
        if model is AgentTask and self.task is not None and self.task.id == pk:
            return self.task
        if model is Conversation:
            return None
        return None

    async def scalar(self, statement: Any) -> Any:  # noqa: ARG002 - 不解析查询
        return self.scalar_value

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj: Any) -> None:
        pass


class FakeSessionFactory:
    """让 ``async with SessionLocal() as db`` 返回固定 FakeSession。"""

    def __init__(self, session: FakeSession) -> None:
        self.session = session

    def __call__(self) -> FakeSessionFactory:
        return self

    async def __aenter__(self) -> FakeSession:
        return self.session

    async def __aexit__(self, *exc_info: Any) -> bool:
        return False


class PublishedEvents:
    """记录 publish_event 调用。"""

    def __init__(self) -> None:
        self.items: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, task_id: Any, event: str, data: dict[str, Any]) -> None:
        self.items.append((event, data))

    @property
    def names(self) -> list[str]:
        return [event for event, _ in self.items]


def make_task(
    *,
    status: str = AgentTaskStatus.RUNNING.value,
    steps: list[dict[str, Any]] | None = None,
    pending_confirm: dict[str, Any] | None = None,
) -> AgentTask:
    """构造一个未绑定真实会话的任务对象。"""
    task = AgentTask(
        conversation_id=uuid4(),
        user_id=uuid4(),
        instruction="给产品经理生成一份 JD",
        status=status,
        current_step_index=0,
        steps=steps or [],
        pending_confirm=pending_confirm,
        error_message=None,
    )
    task.id = uuid4()
    task.is_active = True
    task.created_at = datetime.now(UTC)
    task.updated_at = datetime.now(UTC)
    return task


def make_step(
    index: int,
    tool: str,
    *,
    status: str = AgentStepStatus.PENDING.value,
    args: dict[str, Any] | None = None,
    content: str | None = None,
) -> dict[str, Any]:
    """构造步骤快照。"""
    return {
        "step_index": index,
        "tool": tool,
        "name": tool,
        "status": status,
        "args": args or {},
        "summary": "",
        "result_preview": None,
        "content": content,
        "error": None,
        "editable": True,
    }


@pytest.fixture()
def published(monkeypatch: pytest.MonkeyPatch) -> PublishedEvents:
    """拦截事件发布。"""
    recorder = PublishedEvents()
    monkeypatch.setattr(events, "publish_event", recorder)
    return recorder


# ---------------------------------------------------------------------------
# 挂起与执行
# ---------------------------------------------------------------------------
async def test_confirm_step_suspends_task(published: PublishedEvents) -> None:
    """需要确认的步骤挂起任务并推送 confirm_required，不执行工具。"""
    task = make_task(steps=[make_step(0, "generate_jd", args={"title": "产品经理"})])
    db = FakeSession(task)

    await worker._advance(db, task, 0)

    assert task.status == AgentTaskStatus.WAITING_CONFIRM.value
    assert task.pending_confirm is not None
    assert task.pending_confirm["tool"] == "generate_jd"
    assert task.pending_confirm["editable"] is True
    assert task.steps[0]["status"] == AgentStepStatus.WAITING_CONFIRM.value
    assert "confirm_required" in published.names


async def test_generation_appends_save_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    published: PublishedEvents,
) -> None:
    """生成类步骤完成后自动追加 save_resource 确认步骤并挂起。"""

    async def fake_execute(name: str, args: dict[str, Any], **kwargs: Any) -> tools.ToolResult:
        assert name == "generate_criteria"
        return tools.ToolResult(
            content="评分标准正文",
            preview="评分标准摘要",
            save_payload={
                "resource": "scoring_criteria",
                "data": {"title": "产品经理评分标准", "content": "评分标准正文"},
            },
        )

    monkeypatch.setattr(tools, "execute_tool", fake_execute)
    task = make_task(steps=[make_step(0, "generate_criteria", args={"job_description_id": ""})])
    db = FakeSession(task)

    await worker._advance(db, task, 0)

    assert task.steps[0]["status"] == AgentStepStatus.COMPLETED.value
    assert len(task.steps) == 2
    assert task.steps[1]["tool"] == "save_resource"
    assert task.status == AgentTaskStatus.WAITING_CONFIRM.value
    assert task.pending_confirm is not None
    assert task.pending_confirm["tool"] == "save_resource"


async def test_step_failure_fails_task(
    monkeypatch: pytest.MonkeyPatch,
    published: PublishedEvents,
) -> None:
    """工具执行失败时步骤与任务都标记失败，并推送 task_end。"""

    async def fake_execute(name: str, args: dict[str, Any], **kwargs: Any) -> tools.ToolResult:
        raise AgentToolFailedError("Dify 不可用")

    monkeypatch.setattr(tools, "execute_tool", fake_execute)
    task = make_task(steps=[make_step(0, "generate_criteria", args={"job_description_id": ""})])
    db = FakeSession(task)

    await worker._advance(db, task, 0)

    assert task.status == AgentTaskStatus.FAILED.value
    assert task.steps[0]["status"] == AgentStepStatus.FAILED.value
    assert task.error_message == "Dify 不可用"
    assert published.names[-1] == "task_end"
    assert db.added  # 助手失败消息已落库


# ---------------------------------------------------------------------------
# 确认 / 取消恢复
# ---------------------------------------------------------------------------
def _pending_save_task() -> AgentTask:
    task = make_task(
        status=AgentTaskStatus.WAITING_CONFIRM.value,
        steps=[
            make_step(0, "generate_jd", status="completed", content="JD 正文"),
            make_step(
                1,
                "save_resource",
                status="waiting_confirm",
                args={"resource": "jd", "data": {"title": "产品经理", "content": "JD 正文"}},
            ),
        ],
        pending_confirm={
            "step_index": 1,
            "tool": "save_resource",
            "name": "保存资源",
            "summary": "即将保存 JD",
            "args": {"resource": "jd", "data": {"title": "产品经理", "content": "JD 正文"}},
            "editable": True,
        },
    )
    task.current_step_index = 1
    return task


async def test_resume_confirm_executes_and_completes(
    monkeypatch: pytest.MonkeyPatch,
    published: PublishedEvents,
) -> None:
    """确认后执行保存步骤，任务完成并写助手汇总。"""

    async def fake_execute(name: str, args: dict[str, Any], **kwargs: Any) -> tools.ToolResult:
        assert name == "save_resource"
        return tools.ToolResult(
            content="已保存 JD：产品经理",
            preview="已保存 JD：产品经理",
            persisted=True,
        )

    monkeypatch.setattr(tools, "execute_tool", fake_execute)
    task = _pending_save_task()
    db = FakeSession(task)
    monkeypatch.setattr(worker, "SessionLocal", FakeSessionFactory(db))

    await worker._resume_agent(task.id, "confirm", None)

    assert task.status == AgentTaskStatus.COMPLETED.value
    assert task.pending_confirm is None
    assert task.steps[1]["status"] == AgentStepStatus.COMPLETED.value
    assert db.added
    assert published.names[-1] == "task_end"
    assert published.items[-1][1]["status"] == "completed"


async def test_resume_cancel_cancels_task(
    monkeypatch: pytest.MonkeyPatch,
    published: PublishedEvents,
) -> None:
    """取消后步骤标记取消、任务终止，且不执行工具。"""
    called: list[str] = []

    async def fake_execute(name: str, args: dict[str, Any], **kwargs: Any) -> tools.ToolResult:
        called.append(name)
        return tools.ToolResult()

    monkeypatch.setattr(tools, "execute_tool", fake_execute)
    task = _pending_save_task()
    db = FakeSession(task)
    monkeypatch.setattr(worker, "SessionLocal", FakeSessionFactory(db))

    await worker._resume_agent(task.id, "cancel", None)

    assert called == []
    assert task.status == AgentTaskStatus.CANCELLED.value
    assert task.steps[1]["status"] == AgentStepStatus.CANCELLED.value


# ---------------------------------------------------------------------------
# 快照与汇总
# ---------------------------------------------------------------------------
def test_task_snapshot_matches_read_contract() -> None:
    """快照字段与前端契约一致（含 pending_confirm 与步骤数组）。"""
    task = _pending_save_task()
    snapshot = worker.task_snapshot(task)

    assert snapshot["id"] == str(task.id)
    assert snapshot["status"] == AgentTaskStatus.WAITING_CONFIRM.value
    assert len(snapshot["steps"]) == 2
    assert snapshot["pending_confirm"]["tool"] == "save_resource"


def test_assistant_content_includes_generated_content() -> None:
    """助手汇总消息包含生成正文与已保存结果。"""
    task = _pending_save_task()
    task.steps[1] = {**task.steps[1], "status": "completed", "result_preview": "已保存 JD"}

    content = worker._assistant_content(task, AgentTaskStatus.COMPLETED, None)

    assert "JD 正文" in content
    assert "已保存 JD" in content


def test_assistant_content_failed_uses_error() -> None:
    """失败任务的助手消息使用失败原因。"""
    task = make_task()
    content = worker._assistant_content(task, AgentTaskStatus.FAILED, "Dify 不可用")
    assert content == "Dify 不可用"
