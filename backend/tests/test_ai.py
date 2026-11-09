"""AI 接口层测试：鉴权、类型校验、阻塞调用与 SSE 代理。

Dify 客户端通过 ``dependency_overrides`` 替换为 ``httpx.MockTransport``，
不依赖真实 Dify 服务；数据库依赖同样用 ``FakeSession`` 替代。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.services import dify_service
from tests.fakes import FakeSession, make_user

API = settings.api_v1_prefix


class MockDify:
    """记录请求并按路径返回预置响应的 httpx MockTransport handler。"""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.responder: Callable[[httpx.Request], httpx.Response] = self._default

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responder(request)

    @staticmethod
    def _default(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/chat-messages"):
            body = json.loads(request.content)
            if body.get("response_mode") == "streaming":
                return httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=(
                        b'data: {"event":"message","answer":"hi",'
                        b'"conversation_id":"conv-1"}\n\n'
                        b'data: {"event":"message_end"}\n\n'
                    ),
                )
            return httpx.Response(
                200,
                json={
                    "event": "message",
                    "task_id": "task-1",
                    "message_id": "msg-1",
                    "conversation_id": "conv-1",
                    "mode": "advanced-chat",
                    "answer": "这是一份 JD",
                    "created_at": 1_700_000_000,
                    "metadata": {"usage": {"total_tokens": 12}},
                },
            )
        if path.endswith("/parameters"):
            return httpx.Response(
                200,
                json={
                    "opening_statement": "你好",
                    "suggested_questions": ["生成 JD"],
                    "user_input_form": [{"number": {"variable": "type"}}],
                },
            )
        return httpx.Response(404, json={"code": "not_found", "message": "unknown path"})


@pytest.fixture()
def ai_client() -> Iterator[tuple[TestClient, FakeSession, MockDify]]:
    session = FakeSession(make_user())
    mock = MockDify()

    async def _override_get_db() -> AsyncIterator[FakeSession]:
        yield session

    def _override_get_client() -> httpx.AsyncClient:
        # 每次请求创建独立客户端，避免测试线程与 pytest 事件循环的绑定问题
        return httpx.AsyncClient(transport=httpx.MockTransport(mock), timeout=5.0)

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[dify_service.get_client] = _override_get_client
    try:
        with TestClient(app) as client:
            yield client, session, mock
    finally:
        app.dependency_overrides.clear()


def auth_headers(session: FakeSession) -> dict[str, str]:
    assert session.user is not None
    return {"Authorization": f"Bearer {create_access_token(session.user.id)}"}


# ---------------------------------------------------------------------------
# 元数据接口
# ---------------------------------------------------------------------------
def test_ai_endpoints_require_auth(ai_client: tuple[TestClient, FakeSession, MockDify]) -> None:
    client, _, _ = ai_client

    response = client.get(f"{API}/ai/types")

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_TOKEN"


def test_list_workflow_types(ai_client: tuple[TestClient, FakeSession, MockDify]) -> None:
    client, session, _ = ai_client

    response = client.get(f"{API}/ai/types", headers=auth_headers(session))

    assert response.status_code == 200
    body = response.json()
    assert [item["type"] for item in body] == [1, 2, 3, 4, 5, 6]
    assert body[0]["key"] == "jd_generation"
    assert body[2]["required_inputs"] == ["jianli"]


def test_get_parameters(ai_client: tuple[TestClient, FakeSession, MockDify]) -> None:
    client, session, _ = ai_client

    response = client.get(f"{API}/ai/parameters", headers=auth_headers(session))

    assert response.status_code == 200
    assert response.json()["opening_statement"] == "你好"
    assert response.json()["user_input_form"]


# ---------------------------------------------------------------------------
# 阻塞调用
# ---------------------------------------------------------------------------
def test_chat_blocking(ai_client: tuple[TestClient, FakeSession, MockDify]) -> None:
    client, session, mock = ai_client

    response = client.post(
        f"{API}/ai/chat",
        headers=auth_headers(session),
        json={"type": 1, "query": "招聘前端工程师"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == 1
    assert body["answer"] == "这是一份 JD"
    assert body["conversation_id"] == "conv-1"
    assert body["usage"]["total_tokens"] == 12

    sent = json.loads(mock.requests[-1].content)
    assert sent["inputs"]["type"] == 1
    assert sent["response_mode"] == "blocking"
    assert sent["user"] == str(session.user.id)


def test_chat_type4_allows_empty_query(
    ai_client: tuple[TestClient, FakeSession, MockDify],
) -> None:
    client, session, mock = ai_client

    response = client.post(
        f"{API}/ai/chat",
        headers=auth_headers(session),
        json={
            "type": 4,
            "query": "",
            "inputs": {"jd": "岗位职责", "jianli": "候选人简历"},
        },
    )

    assert response.status_code == 200
    assert response.json()["type"] == 4
    sent = json.loads(mock.requests[-1].content)
    assert sent["query"] == "请根据 JD 和简历生成面试方案与面试题"


def test_chat_rejects_missing_required_input(
    ai_client: tuple[TestClient, FakeSession, MockDify],
) -> None:
    client, session, mock = ai_client

    response = client.post(
        f"{API}/ai/chat",
        headers=auth_headers(session),
        json={"type": 3, "query": "评价标准"},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "WORKFLOW_VALIDATION_ERROR"
    assert body["details"]["missing_inputs"] == ["jianli"]
    assert mock.requests == []


def test_chat_rejects_unknown_type(ai_client: tuple[TestClient, FakeSession, MockDify]) -> None:
    client, session, mock = ai_client

    response = client.post(
        f"{API}/ai/chat",
        headers=auth_headers(session),
        json={"type": 7, "query": "x"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert mock.requests == []


def test_chat_maps_dify_400(ai_client: tuple[TestClient, FakeSession, MockDify]) -> None:
    client, session, mock = ai_client

    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": "invalid_param", "message": "bad inputs"})

    mock.responder = responder

    response = client.post(
        f"{API}/ai/chat",
        headers=auth_headers(session),
        json={"type": 1, "query": "招聘前端工程师"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "DIFY_INVALID_PARAM"


def test_chat_maps_dify_500(ai_client: tuple[TestClient, FakeSession, MockDify]) -> None:
    client, session, mock = ai_client

    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"code": "internal_error", "message": "boom"})

    mock.responder = responder

    response = client.post(
        f"{API}/ai/chat",
        headers=auth_headers(session),
        json={"type": 1, "query": "招聘前端工程师"},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "DIFY_UNAVAILABLE"


# ---------------------------------------------------------------------------
# 流式调用
# ---------------------------------------------------------------------------
def test_chat_stream(ai_client: tuple[TestClient, FakeSession, MockDify]) -> None:
    client, session, mock = ai_client

    with client.stream(
        "POST",
        f"{API}/ai/chat/stream",
        headers=auth_headers(session),
        json={"type": 1, "query": "招聘前端工程师"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())

    assert '"event":"message"' in body
    assert '"event":"message_end"' in body

    sent = json.loads(mock.requests[-1].content)
    assert sent["response_mode"] == "streaming"


def test_chat_stream_upstream_error_becomes_error_event(
    ai_client: tuple[TestClient, FakeSession, MockDify],
) -> None:
    client, session, mock = ai_client

    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"code": "internal_error", "message": "boom"})

    mock.responder = responder

    with client.stream(
        "POST",
        f"{API}/ai/chat/stream",
        headers=auth_headers(session),
        json={"type": 1, "query": "招聘前端工程师"},
    ) as response:
        body = "".join(response.iter_text())

    event: dict[str, Any] = json.loads(body.removeprefix("data: ").strip())
    assert event["event"] == "error"
    assert event["code"] == "DIFY_UNAVAILABLE"


def test_chat_stream_rejects_missing_input_before_stream(
    ai_client: tuple[TestClient, FakeSession, MockDify],
) -> None:
    client, session, mock = ai_client

    response = client.post(
        f"{API}/ai/chat/stream",
        headers=auth_headers(session),
        json={"type": 3, "query": "评价标准"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "WORKFLOW_VALIDATION_ERROR"
    assert mock.requests == []


# ---------------------------------------------------------------------------
# OpenAPI
# ---------------------------------------------------------------------------
def test_openapi_documents_ai_endpoints(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert f"{API}/ai/types" in paths
    assert f"{API}/ai/parameters" in paths
    assert f"{API}/ai/chat" in paths
    assert f"{API}/ai/chat/stream" in paths
