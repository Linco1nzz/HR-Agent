"""问答会话接口测试：鉴权、CRUD 组装与 SSE 事件流（mock service，不依赖数据库）。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.exceptions import ConversationNotFoundError
from app.core.security import create_access_token
from app.db.models import Conversation, Message
from app.db.session import get_db
from app.main import app
from app.schemas.conversation import MessageFeedback
from app.services import conversation_service, qa_service
from tests.fakes import FakeSession, make_user

API = settings.api_v1_prefix


def make_conversation_record(user_id: UUID, **overrides: Any) -> Conversation:
    now = datetime.now(UTC)
    data: dict[str, Any] = {
        "id": uuid4(),
        "title": "新会话",
        "kind": "knowledge",
        "description": None,
        "status": "active",
        "knowledge_base_ids": [],
        "total_messages": 0,
        "meta_data": None,
        "user_id": user_id,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return Conversation(**data)


def make_message_record(conversation_id: UUID, **overrides: Any) -> Message:
    data: dict[str, Any] = {
        "id": uuid4(),
        "conversation_id": conversation_id,
        "role": "assistant",
        "content": "年假有 5 天 [1]",
        "model_name": "deepseek-flash",
        "tokens_used": 15,
        "response_time": 1.2,
        "context": {"route": "kb", "sources": []},
        "meta_data": None,
        "rating": None,
        "feedback": None,
        "parent_message_id": None,
        "created_at": datetime.now(UTC),
    }
    data.update(overrides)
    return Message(**data)


@pytest.fixture()
def conversation_client() -> Iterator[tuple[TestClient, FakeSession]]:
    session = FakeSession(make_user())

    async def _override_get_db() -> AsyncIterator[FakeSession]:
        yield session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as client:
            yield client, session
    finally:
        app.dependency_overrides.clear()


def auth_headers(session: FakeSession) -> dict[str, str]:
    assert session.user is not None
    return {"Authorization": f"Bearer {create_access_token(session.user.id)}"}


# ---------------------------------------------------------------------------
# 鉴权与 OpenAPI
# ---------------------------------------------------------------------------
def test_conversation_endpoints_require_auth(client: TestClient) -> None:
    conversation_id = uuid4()
    assert client.get(f"{API}/conversations").status_code == 401
    assert client.post(f"{API}/conversations", json={}).status_code == 401
    assert client.get(f"{API}/conversations/{conversation_id}").status_code == 401
    assert (
        client.post(
            f"{API}/conversations/{conversation_id}/chat", json={"content": "你好"}
        ).status_code
        == 401
    )
    assert client.get(f"{API}/conversations").json()["code"] == "INVALID_TOKEN"


def test_openapi_conversation_endpoints(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert f"{API}/conversations" in paths
    assert f"{API}/conversations/{{conversation_id}}" in paths
    assert f"{API}/conversations/{{conversation_id}}/messages" in paths
    assert f"{API}/conversations/{{conversation_id}}/messages/{{message_id}}/feedback" in paths
    assert f"{API}/conversations/{{conversation_id}}/chat" in paths


# ---------------------------------------------------------------------------
# CRUD（mock service）
# ---------------------------------------------------------------------------
def test_create_conversation(
    monkeypatch: pytest.MonkeyPatch,
    conversation_client: tuple[TestClient, FakeSession],
) -> None:
    client, session = conversation_client
    assert session.user is not None
    record = make_conversation_record(session.user.id, title="员工手册咨询")
    captured: dict[str, Any] = {}

    async def fake_create(db: Any, payload: Any, *, user: Any) -> Conversation:
        captured["payload"] = payload
        return record

    monkeypatch.setattr(conversation_service, "create_conversation", fake_create)

    response = client.post(
        f"{API}/conversations",
        headers=auth_headers(session),
        json={"title": "员工手册咨询"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"] == str(record.id)
    assert body["title"] == "员工手册咨询"
    assert body["knowledge_base_ids"] == []
    assert captured["payload"].title == "员工手册咨询"


def test_list_conversations_pagination(
    monkeypatch: pytest.MonkeyPatch,
    conversation_client: tuple[TestClient, FakeSession],
) -> None:
    client, session = conversation_client
    assert session.user is not None
    records = [make_conversation_record(session.user.id) for _ in range(2)]

    async def fake_list(
        db: Any, *, page: int, page_size: int, user: Any, kind: str | None = None
    ) -> tuple[list, int]:
        assert page == 2 and page_size == 5
        return records, 7

    monkeypatch.setattr(conversation_service, "list_conversations", fake_list)

    response = client.get(
        f"{API}/conversations",
        headers=auth_headers(session),
        params={"page": 2, "page_size": 5},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 7
    assert body["page"] == 2
    assert body["page_size"] == 5
    assert len(body["items"]) == 2


def test_get_conversation_not_found(
    monkeypatch: pytest.MonkeyPatch,
    conversation_client: tuple[TestClient, FakeSession],
) -> None:
    client, session = conversation_client

    async def fake_get(db: Any, conversation_id: UUID, *, user: Any) -> Conversation:
        raise ConversationNotFoundError()

    monkeypatch.setattr(conversation_service, "get_conversation", fake_get)

    response = client.get(f"{API}/conversations/{uuid4()}", headers=auth_headers(session))

    assert response.status_code == 404
    assert response.json()["code"] == "CONVERSATION_NOT_FOUND"


def test_update_and_delete_conversation(
    monkeypatch: pytest.MonkeyPatch,
    conversation_client: tuple[TestClient, FakeSession],
) -> None:
    client, session = conversation_client
    assert session.user is not None
    record = make_conversation_record(session.user.id, status="archived")

    async def fake_update(
        db: Any, conversation_id: UUID, payload: Any, *, user: Any
    ) -> Conversation:
        assert payload.status == "archived"
        return record

    async def fake_delete(db: Any, conversation_id: UUID, *, user: Any) -> None:
        return None

    monkeypatch.setattr(conversation_service, "update_conversation", fake_update)
    monkeypatch.setattr(conversation_service, "delete_conversation", fake_delete)

    patched = client.patch(
        f"{API}/conversations/{record.id}",
        headers=auth_headers(session),
        json={"status": "archived"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["status"] == "archived"

    deleted = client.delete(f"{API}/conversations/{record.id}", headers=auth_headers(session))
    assert deleted.status_code == 204


def test_list_messages_and_feedback(
    monkeypatch: pytest.MonkeyPatch,
    conversation_client: tuple[TestClient, FakeSession],
) -> None:
    client, session = conversation_client
    assert session.user is not None
    conversation = make_conversation_record(session.user.id)
    message = make_message_record(conversation.id)

    async def fake_list(
        db: Any, conversation_id: UUID, *, page: int, page_size: int, user: Any
    ) -> tuple[list, int]:
        return [message], 1

    async def fake_feedback(
        db: Any, conversation_id: UUID, message_id: UUID, payload: MessageFeedback, *, user: Any
    ) -> Message:
        assert message_id == message.id
        message.rating = payload.rating
        message.feedback = payload.feedback
        return message

    monkeypatch.setattr(conversation_service, "list_messages", fake_list)
    monkeypatch.setattr(conversation_service, "update_message_feedback", fake_feedback)

    listed = client.get(
        f"{API}/conversations/{conversation.id}/messages",
        headers=auth_headers(session),
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(message.id)
    assert body["items"][0]["context"] == {"route": "kb", "sources": []}

    feedback = client.patch(
        f"{API}/conversations/{conversation.id}/messages/{message.id}/feedback",
        headers=auth_headers(session),
        json={"rating": 5, "feedback": "很有帮助"},
    )
    assert feedback.status_code == 200, feedback.text
    assert feedback.json()["rating"] == 5

    invalid = client.patch(
        f"{API}/conversations/{conversation.id}/messages/{message.id}/feedback",
        headers=auth_headers(session),
        json={"rating": 6},
    )
    assert invalid.status_code == 422


# ---------------------------------------------------------------------------
# SSE 流式问答（httpx ASGITransport 直连 app）
# ---------------------------------------------------------------------------
@pytest.fixture()
def sse_session() -> Iterator[FakeSession]:
    session = FakeSession(make_user())

    async def _override_get_db() -> AsyncIterator[FakeSession]:
        yield session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield session
    finally:
        app.dependency_overrides.clear()


def parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in text.strip().split("\n\n"):
        lines = block.splitlines()
        name = next(line[len("event: ") :] for line in lines if line.startswith("event: "))
        data = next(line[len("data: ") :] for line in lines if line.startswith("data: "))
        events.append((name, json.loads(data)))
    return events


async def test_chat_sse_event_sequence(
    monkeypatch: pytest.MonkeyPatch,
    sse_session: FakeSession,
) -> None:
    conversation_id = uuid4()
    user_message_id, assistant_message_id = uuid4(), uuid4()

    async def fake_get(db: Any, cid: UUID, *, user: Any) -> Conversation:
        assert cid == conversation_id
        return make_conversation_record(user.id, id=conversation_id)

    async def fake_chat(cid: UUID, content: str, *, user: Any) -> AsyncIterator[tuple[str, dict]]:
        assert cid == conversation_id
        assert content == "年假有几天"
        yield "meta", {
            "user_message_id": str(user_message_id),
            "assistant_message_id": str(assistant_message_id),
            "route": "kb",
            "reason": "涉及员工手册",
            "rewritten_query": "员工手册年假规定",
            "keywords": ["年假"],
        }
        yield "sources", {"sources": [{"document_name": "员工手册.txt", "score": 0.87}]}
        yield "delta", {"content": "年假"}
        yield "delta", {"content": "有 5 天 [1]"}
        yield "done", {
            "message_id": str(assistant_message_id),
            "tokens_used": 15,
            "response_time": 1.2,
            "model_name": "deepseek-flash",
        }

    monkeypatch.setattr(conversation_service, "get_conversation", fake_get)
    monkeypatch.setattr(qa_service, "chat", fake_chat)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"{API}/conversations/{conversation_id}/chat",
            headers=auth_headers(sse_session),
            json={"content": "年假有几天"},
        )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"

    events = parse_sse(response.text)
    assert [name for name, _ in events] == ["meta", "sources", "delta", "delta", "done"]
    assert events[0][1]["route"] == "kb"
    assert events[1][1]["sources"][0]["score"] == 0.87
    assert "".join(data["content"] for name, data in events if name == "delta") == "年假有 5 天 [1]"
    assert events[-1][1]["message_id"] == str(assistant_message_id)
    # ensure_ascii=False：中文原样输出
    assert "年假" in response.text


async def test_chat_sse_error_event(
    monkeypatch: pytest.MonkeyPatch,
    sse_session: FakeSession,
) -> None:
    conversation_id = uuid4()

    async def fake_get(db: Any, cid: UUID, *, user: Any) -> Conversation:
        return make_conversation_record(user.id, id=conversation_id)

    async def fake_chat(cid: UUID, content: str, *, user: Any) -> AsyncIterator[tuple[str, dict]]:
        yield "error", {"code": "QA_STREAM_FAILED", "message": "回答生成失败，请稍后重试"}

    monkeypatch.setattr(conversation_service, "get_conversation", fake_get)
    monkeypatch.setattr(qa_service, "chat", fake_chat)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"{API}/conversations/{conversation_id}/chat",
            headers=auth_headers(sse_session),
            json={"content": "年假有几天"},
        )

    assert response.status_code == 200
    events = parse_sse(response.text)
    assert events == [
        ("error", {"code": "QA_STREAM_FAILED", "message": "回答生成失败，请稍后重试"})
    ]


async def test_chat_unknown_conversation_returns_404(
    monkeypatch: pytest.MonkeyPatch,
    sse_session: FakeSession,
) -> None:
    async def fake_get(db: Any, cid: UUID, *, user: Any) -> Conversation:
        raise ConversationNotFoundError()

    monkeypatch.setattr(conversation_service, "get_conversation", fake_get)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"{API}/conversations/{uuid4()}/chat",
            headers=auth_headers(sse_session),
            json={"content": "年假有几天"},
        )

    assert response.status_code == 404
    assert response.json()["code"] == "CONVERSATION_NOT_FOUND"


async def test_chat_empty_content_rejected(sse_session: FakeSession) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"{API}/conversations/{uuid4()}/chat",
            headers=auth_headers(sse_session),
            json={"content": "   "},
        )

    assert response.status_code == 422
