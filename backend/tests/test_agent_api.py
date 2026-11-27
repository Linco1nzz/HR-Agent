"""Agent 接口测试：鉴权、任务创建、确认、SSE 快照与上传（mock service，不依赖数据库）。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints import agent as agent_endpoint
from app.core.config import settings
from app.core.security import create_access_token
from app.db.models import AgentTask, Conversation, Message, User
from app.db.session import get_db
from app.main import app
from app.schemas.agent import AgentResumeUploadResponse, AgentTaskStatus
from app.services import conversation_service
from app.services.agent import task_service, uploads, worker
from tests.fakes import make_user

API = settings.api_v1_prefix


class FakeApiSession:
    """覆盖 Agent 接口用到的 AsyncSession 子集。"""

    def __init__(self, user: User) -> None:
        self.user = user
        self.added: list[Any] = []
        self.commits = 0
        self.conversation: Conversation | None = None
        self.task: AgentTask | None = None

    async def get(self, model: type, pk: Any) -> Any:
        if model is User and pk == self.user.id:
            return self.user
        if model is Conversation and self.conversation is not None:
            return self.conversation if self.conversation.id == pk else None
        if model is AgentTask and self.task is not None:
            return self.task if self.task.id == pk else None
        return None

    async def scalar(self, statement: Any) -> Any:
        # 鉴权走 user_service 的 ``SELECT ... FROM users``；其余计数查询返回 0
        if "FROM users" in str(statement):
            return self.user
        return 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj: Any) -> None:
        pass


def make_conversation(user_id: UUID, kind: str = "agent") -> Conversation:
    now = datetime.now(UTC)
    record = Conversation(
        title="新会话",
        kind=kind,
        status="active",
        knowledge_base_ids=[],
        total_messages=0,
        user_id=user_id,
        is_active=True,
    )
    record.id = uuid4()
    record.created_at = now
    record.updated_at = now
    return record


def make_agent_task(
    *,
    user_id: UUID,
    status: str = AgentTaskStatus.WAITING_CONFIRM.value,
    steps: list[dict[str, Any]] | None = None,
    pending_confirm: dict[str, Any] | None = None,
) -> AgentTask:
    now = datetime.now(UTC)
    task = AgentTask(
        conversation_id=uuid4(),
        user_id=user_id,
        instruction="给产品经理生成 JD",
        status=status,
        current_step_index=0,
        steps=steps or [],
        pending_confirm=pending_confirm,
        error_message=None,
    )
    task.id = uuid4()
    task.is_active = True
    task.created_at = now
    task.updated_at = now
    return task


class _FakeSessionContext:
    """让 ``async with SessionLocal() as db`` 复用测试替身。"""

    def __init__(self, session: FakeApiSession) -> None:
        self.session = session

    async def __aenter__(self) -> FakeApiSession:
        return self.session

    async def __aexit__(self, *exc_info: Any) -> bool:
        return False


@pytest.fixture()
def api_client() -> Iterator[tuple[TestClient, FakeApiSession]]:
    """带登录态与数据库替身的测试客户端。"""
    session = FakeApiSession(make_user())

    async def _override_get_db() -> AsyncIterator[FakeApiSession]:
        yield session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as client:
            yield client, session
    finally:
        app.dependency_overrides.clear()


def auth_headers(session: FakeApiSession) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(session.user.id)}"}


# ---------------------------------------------------------------------------
# 鉴权与 OpenAPI
# ---------------------------------------------------------------------------
def test_agent_endpoints_require_auth(client: TestClient) -> None:
    task_id = uuid4()
    assert (
        client.post(f"{API}/agent/chat", json={"conversation_id": str(uuid4())}).status_code == 401
    )
    assert client.get(f"{API}/agent/stream/{task_id}").status_code == 401
    assert client.post(f"{API}/agent/confirm", json={"task_id": str(task_id)}).status_code == 401
    assert client.get(f"{API}/agent/tasks/{task_id}").status_code == 401
    assert client.post(f"{API}/agent/uploads/resume").status_code == 401


def test_openapi_agent_paths(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert f"{API}/agent/chat" in paths
    assert f"{API}/agent/stream/{{task_id}}" in paths
    assert f"{API}/agent/confirm" in paths
    assert f"{API}/agent/tasks/{{task_id}}" in paths
    assert f"{API}/agent/uploads/resume" in paths


# ---------------------------------------------------------------------------
# 发起任务
# ---------------------------------------------------------------------------
def test_create_agent_task(
    monkeypatch: pytest.MonkeyPatch,
    api_client: tuple[TestClient, FakeApiSession],
) -> None:
    """创建任务立即返回 task_id，并写入用户消息。"""
    client, session = api_client
    conversation = make_conversation(session.user.id)
    session.conversation = conversation

    async def fake_get_conversation(db: Any, conversation_id: UUID, *, user: Any) -> Conversation:
        return conversation

    async def fake_find_active(db: Any, conversation_id: UUID) -> None:
        return None

    async def fake_create_task(db: Any, **kwargs: Any) -> AgentTask:
        return make_agent_task(user_id=session.user.id, status=AgentTaskStatus.CREATED.value)

    async def fake_run_agent(task_id: UUID) -> None:
        return None

    monkeypatch.setattr(conversation_service, "get_conversation", fake_get_conversation)
    monkeypatch.setattr(task_service, "find_active_task", fake_find_active)
    monkeypatch.setattr(task_service, "create_task", fake_create_task)
    monkeypatch.setattr(worker, "run_agent", fake_run_agent)

    response = client.post(
        f"{API}/agent/chat",
        headers=auth_headers(session),
        json={"conversation_id": str(conversation.id), "content": "给产品经理生成一份 JD"},
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "created"
    assert body["task_id"]
    user_messages = [item for item in session.added if isinstance(item, Message)]
    assert user_messages and user_messages[0].content == "给产品经理生成一份 JD"


def test_create_agent_task_rejects_knowledge_conversation(
    monkeypatch: pytest.MonkeyPatch,
    api_client: tuple[TestClient, FakeApiSession],
) -> None:
    """知识问答会话不能发起 Agent 任务。"""
    client, session = api_client
    conversation = make_conversation(session.user.id, kind="knowledge")
    session.conversation = conversation

    async def fake_get_conversation(db: Any, conversation_id: UUID, *, user: Any) -> Conversation:
        return conversation

    monkeypatch.setattr(conversation_service, "get_conversation", fake_get_conversation)

    response = client.post(
        f"{API}/agent/chat",
        headers=auth_headers(session),
        json={"conversation_id": str(conversation.id), "content": "生成 JD"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "BAD_REQUEST"


def test_create_agent_task_rejects_concurrent_task(
    monkeypatch: pytest.MonkeyPatch,
    api_client: tuple[TestClient, FakeApiSession],
) -> None:
    """上一个任务未结束时拒绝新指令。"""
    client, session = api_client
    conversation = make_conversation(session.user.id)
    session.conversation = conversation
    running = make_agent_task(user_id=session.user.id, status=AgentTaskStatus.RUNNING.value)

    async def fake_get_conversation(db: Any, conversation_id: UUID, *, user: Any) -> Conversation:
        return conversation

    async def fake_find_active(db: Any, conversation_id: UUID) -> AgentTask:
        return running

    monkeypatch.setattr(conversation_service, "get_conversation", fake_get_conversation)
    monkeypatch.setattr(task_service, "find_active_task", fake_find_active)

    response = client.post(
        f"{API}/agent/chat",
        headers=auth_headers(session),
        json={"conversation_id": str(conversation.id), "content": "再生成一份"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "AGENT_TASK_STATE_CONFLICT"


# ---------------------------------------------------------------------------
# 确认
# ---------------------------------------------------------------------------
def test_confirm_requires_waiting_state(
    monkeypatch: pytest.MonkeyPatch,
    api_client: tuple[TestClient, FakeApiSession],
) -> None:
    """任务不在 waiting_confirm 时返回 409。"""
    client, session = api_client
    task = make_agent_task(user_id=session.user.id, status=AgentTaskStatus.COMPLETED.value)

    async def fake_get_task_for_user(db: Any, task_id: UUID, user_id: UUID) -> AgentTask:
        return task

    monkeypatch.setattr(task_service, "get_task_for_user", fake_get_task_for_user)

    response = client.post(
        f"{API}/agent/confirm",
        headers=auth_headers(session),
        json={"task_id": str(task.id), "action": "confirm"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "AGENT_TASK_STATE_CONFLICT"


def test_confirm_accepts_edited_params(
    monkeypatch: pytest.MonkeyPatch,
    api_client: tuple[TestClient, FakeApiSession],
) -> None:
    """确认时可提交修改后的参数，Worker 后台续跑。"""
    client, session = api_client
    pending = {
        "step_index": 0,
        "tool": "generate_jd",
        "name": "生成 JD",
        "summary": "即将生成 JD：产品经理",
        "args": {"title": "产品经理"},
        "editable": True,
    }
    task = make_agent_task(
        user_id=session.user.id,
        steps=[
            {
                "step_index": 0,
                "tool": "generate_jd",
                "name": "生成 JD",
                "status": "waiting_confirm",
                "args": {"title": "产品经理"},
                "summary": "",
                "result_preview": None,
                "content": None,
                "error": None,
                "editable": True,
            }
        ],
        pending_confirm=pending,
    )
    captured: dict[str, Any] = {}

    async def fake_get_task_for_user(db: Any, task_id: UUID, user_id: UUID) -> AgentTask:
        return task

    async def fake_resume(task_id: UUID, action: str, params: dict[str, Any] | None) -> None:
        captured["action"] = action
        captured["params"] = params

    monkeypatch.setattr(task_service, "get_task_for_user", fake_get_task_for_user)
    monkeypatch.setattr(worker, "resume_agent", fake_resume)

    response = client.post(
        f"{API}/agent/confirm",
        headers=auth_headers(session),
        json={
            "task_id": str(task.id),
            "action": "confirm",
            "params": {"title": "高级产品经理"},
        },
    )

    assert response.status_code == 202, response.text
    assert captured["action"] == "confirm"
    assert captured["params"] == {"title": "高级产品经理"}


# ---------------------------------------------------------------------------
# 任务快照与 SSE
# ---------------------------------------------------------------------------
def test_read_task_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    api_client: tuple[TestClient, FakeApiSession],
) -> None:
    """读取任务快照返回步骤与待确认动作。"""
    client, session = api_client
    task = make_agent_task(user_id=session.user.id, steps=[], pending_confirm=None)

    async def fake_get_task_for_user(db: Any, task_id: UUID, user_id: UUID) -> AgentTask:
        return task

    monkeypatch.setattr(task_service, "get_task_for_user", fake_get_task_for_user)

    response = client.get(f"{API}/agent/tasks/{task.id}", headers=auth_headers(session))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(task.id)
    assert body["status"] == AgentTaskStatus.WAITING_CONFIRM.value


def test_stream_terminal_task_emits_snapshot_and_end(
    monkeypatch: pytest.MonkeyPatch,
    api_client: tuple[TestClient, FakeApiSession],
) -> None:
    """已结束任务订阅 SSE 时直接返回快照 + task_end，不挂起连接。"""
    client, session = api_client
    task = make_agent_task(
        user_id=session.user.id,
        status=AgentTaskStatus.COMPLETED.value,
    )
    session.task = task

    async def fake_get_task_for_user(db: Any, task_id: UUID, user_id: UUID) -> AgentTask:
        return task

    async def fake_get_task(db: Any, task_id: UUID) -> AgentTask:
        return task

    monkeypatch.setattr(task_service, "get_task_for_user", fake_get_task_for_user)
    monkeypatch.setattr(task_service, "get_task", fake_get_task)
    monkeypatch.setattr(
        agent_endpoint,
        "SessionLocal",
        lambda: _FakeSessionContext(session),
    )

    response = client.get(f"{API}/agent/stream/{task.id}", headers=auth_headers(session))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "event: task_started" in body
    assert "event: task_end" in body
    assert "completed" in body


# ---------------------------------------------------------------------------
# 表单内简历上传
# ---------------------------------------------------------------------------
def test_read_active_task(
    monkeypatch: pytest.MonkeyPatch,
    api_client: tuple[TestClient, FakeApiSession],
) -> None:
    """刷新后按会话恢复未结束任务；没有任务时返回 null。"""
    client, session = api_client
    conversation = make_conversation(session.user.id)
    task = make_agent_task(user_id=session.user.id, status=AgentTaskStatus.RUNNING.value)

    async def fake_get_conversation(db: Any, conversation_id: UUID, *, user: Any) -> Conversation:
        return conversation

    async def fake_find_active(db: Any, conversation_id: UUID) -> AgentTask | None:
        return task

    monkeypatch.setattr(conversation_service, "get_conversation", fake_get_conversation)
    monkeypatch.setattr(task_service, "find_active_task", fake_find_active)

    response = client.get(
        f"{API}/agent/conversations/{conversation.id}/active-task",
        headers=auth_headers(session),
    )
    assert response.status_code == 200, response.text
    assert response.json()["id"] == str(task.id)

    async def fake_none(db: Any, conversation_id: UUID) -> None:
        return None

    monkeypatch.setattr(task_service, "find_active_task", fake_none)
    empty = client.get(
        f"{API}/agent/conversations/{conversation.id}/active-task",
        headers=auth_headers(session),
    )
    assert empty.status_code == 200
    assert empty.json() is None


def test_upload_resume_in_confirm_form(
    monkeypatch: pytest.MonkeyPatch,
    api_client: tuple[TestClient, FakeApiSession],
) -> None:
    """上传接口只解析不评分，返回 upload_id。"""
    client, session = api_client

    async def fake_save(filename: str, content: bytes) -> AgentResumeUploadResponse:
        assert filename.endswith(".txt")
        assert content
        return AgentResumeUploadResponse(upload_id="abc123", filename=filename, resume_chars=20)

    monkeypatch.setattr(uploads, "save_upload", fake_save)

    response = client.post(
        f"{API}/agent/uploads/resume",
        headers=auth_headers(session),
        files={"file": ("张三.txt", b"resume text", "text/plain")},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["upload_id"] == "abc123"
    assert body["resume_chars"] == 20
