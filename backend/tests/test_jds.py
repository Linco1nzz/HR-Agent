"""JD 接口层测试：鉴权、AI 生成与错误映射（不依赖数据库 / 真实 Dify）。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.exceptions import DifyUnavailableError
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.schemas.ai import ChatResponse, WorkflowType
from app.services import dify_service
from tests.fakes import FakeSession, make_user

API = settings.api_v1_prefix


@pytest.fixture()
def jd_client() -> Iterator[tuple[TestClient, FakeSession]]:
    session = FakeSession(make_user())

    async def _override_get_db() -> AsyncIterator[FakeSession]:
        yield session

    app.dependency_overrides[get_db] = _override_get_db
    # 生成接口只使用 current_user，不需要真实 Dify 客户端
    app.dependency_overrides[dify_service.get_client] = lambda: httpx.AsyncClient()
    try:
        with TestClient(app) as client:
            yield client, session
    finally:
        app.dependency_overrides.clear()


def auth_headers(session: FakeSession) -> dict[str, str]:
    assert session.user is not None
    return {"Authorization": f"Bearer {create_access_token(session.user.id)}"}


def test_generate_jd(
    monkeypatch: pytest.MonkeyPatch,
    jd_client: tuple[TestClient, FakeSession],
) -> None:
    client, session = jd_client
    captured: dict[str, Any] = {}

    async def fake_chat(
        request: Any,
        *,
        user_id: UUID | str,
        client: httpx.AsyncClient | None = None,
    ) -> ChatResponse:
        captured["request"] = request
        captured["user_id"] = user_id
        return ChatResponse(
            type=WorkflowType.JD_GENERATION,
            answer="# 前端工程师\n\n## 岗位职责\n负责前端开发",
            conversation_id="conv-1",
            task_id="task-1",
        )

    monkeypatch.setattr(dify_service, "chat", fake_chat)

    response = client.post(
        f"{API}/jds/generate",
        headers=auth_headers(session),
        json={
            "title": "前端工程师",
            "department": "产品研发",
            "skills": ["Vue 3", "TypeScript"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["content"].startswith("# 前端工程师")
    assert body["conversation_id"] == "conv-1"
    assert body["workflow_type"] == "jd_generation"

    request = captured["request"]
    assert request.type == WorkflowType.JD_GENERATION
    assert "前端工程师" in request.query
    assert "Vue 3、TypeScript" in request.query
    assert captured["user_id"] == session.user.id  # type: ignore[union-attr]


def test_generate_jd_requires_title(
    monkeypatch: pytest.MonkeyPatch, jd_client: tuple[TestClient, FakeSession]
) -> None:
    client, session = jd_client

    response = client.post(
        f"{API}/jds/generate",
        headers=auth_headers(session),
        json={"title": "   "},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_generate_jd_requires_auth(jd_client: tuple[TestClient, FakeSession]) -> None:
    client, _ = jd_client

    response = client.post(f"{API}/jds/generate", json={"title": "前端工程师"})

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_TOKEN"


def test_generate_jd_maps_dify_error(
    monkeypatch: pytest.MonkeyPatch, jd_client: tuple[TestClient, FakeSession]
) -> None:
    client, session = jd_client

    async def fake_chat(
        request: Any,
        *,
        user_id: UUID | str,
        client: httpx.AsyncClient | None = None,
    ) -> ChatResponse:
        raise DifyUnavailableError("Dify 响应超时")

    monkeypatch.setattr(dify_service, "chat", fake_chat)

    response = client.post(
        f"{API}/jds/generate",
        headers=auth_headers(session),
        json={"title": "前端工程师"},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "DIFY_UNAVAILABLE"


def test_generate_jd_stream(
    monkeypatch: pytest.MonkeyPatch,
    jd_client: tuple[TestClient, FakeSession],
) -> None:
    client, session = jd_client

    async def fake_events(
        request: Any,
        *,
        user_id: UUID | str,
        client: httpx.AsyncClient | None = None,
    ) -> Any:
        yield {
            "event": "workflow_started",
            "conversation_id": "conv-1",
            "task_id": "task-1",
        }
        yield {"event": "message", "answer": "# 前端"}
        yield {"event": "message", "answer": "工程师"}
        yield {"event": "message_end", "metadata": {"usage": {"total_tokens": 8}}}

    monkeypatch.setattr(dify_service, "iter_stream_events", fake_events)

    with client.stream(
        "POST",
        f"{API}/jds/generate/stream",
        headers=auth_headers(session),
        json={"title": "前端工程师"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())

    assert "event: start" in body
    assert "event: delta" in body
    assert '"content": "# 前端"' in body
    assert '"content": "工程师"' in body
    assert "event: done" in body
    assert '"content": "# 前端工程师"' in body
    assert '"conversation_id": "conv-1"' in body


def test_openapi_documents_jd_endpoints(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert f"{API}/jds" in paths
    assert f"{API}/jds/generate" in paths
    assert f"{API}/jds/generate/stream" in paths
    assert f"{API}/jds/{{jd_id}}" in paths
