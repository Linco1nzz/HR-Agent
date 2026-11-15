"""会话集成测试：真实 PostgreSQL 下的会话 / 消息 CRUD、归属与级联删除。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.security import get_password_hash

API = settings.api_v1_prefix


def _sync_database_url() -> str:
    url = make_url(settings.database_url).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


def _insert_user(user_id: UUID, username: str, password: str) -> None:
    with psycopg.connect(_sync_database_url()) as conn:
        conn.execute(
            """
            INSERT INTO users
                (id, username, email, full_name, hashed_password,
                 is_verified, is_superuser, is_active)
            VALUES (%s, %s, %s, %s, %s, true, false, true)
            """,
            (user_id, username, f"{username}@example.com", username, get_password_hash(password)),
        )
        conn.commit()


def _insert_message(
    conversation_id: UUID,
    role: str,
    content: str,
    created_at: datetime,
    parent_message_id: UUID | None = None,
) -> UUID:
    message_id = uuid4()
    with psycopg.connect(_sync_database_url()) as conn:
        conn.execute(
            """
            INSERT INTO messages
                (id, conversation_id, role, content, parent_message_id, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (message_id, conversation_id, role, content, parent_message_id, created_at, created_at),
        )
        conn.commit()
    return message_id


def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post(f"{API}/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.integration
def test_conversation_message_flow(client: TestClient) -> None:
    suffix = uuid4().hex[:8]
    password = "Conv-test-123"
    owner_id, other_id = uuid4(), uuid4()
    owner_name, other_name = f"conv_owner_{suffix}", f"conv_other_{suffix}"
    _insert_user(owner_id, owner_name, password)
    _insert_user(other_id, other_name, password)
    conversation_ids: list[UUID] = []

    try:
        owner = _login(client, owner_name, password)
        other = _login(client, other_name, password)

        # --- 创建：默认标题 ---
        created = client.post(f"{API}/conversations", headers=owner, json={})
        assert created.status_code == 201, created.text
        conversation = created.json()
        conversation_id = UUID(conversation["id"])
        conversation_ids.append(conversation_id)
        assert conversation["title"] == "新会话"
        assert conversation["status"] == "active"
        assert conversation["knowledge_base_ids"] == []
        assert conversation["total_messages"] == 0

        # --- 列表：仅本人可见，按更新时间倒序 ---
        listed = client.get(f"{API}/conversations", headers=owner)
        assert listed.status_code == 200, listed.text
        assert any(item["id"] == str(conversation_id) for item in listed.json()["items"])
        other_listed = client.get(f"{API}/conversations", headers=other)
        assert all(item["id"] != str(conversation_id) for item in other_listed.json()["items"])

        # --- 归属：他人访问按 404 处理 ---
        assert (
            client.get(f"{API}/conversations/{conversation_id}", headers=other).status_code == 404
        )
        assert (
            client.delete(f"{API}/conversations/{conversation_id}", headers=other).status_code
            == 404
        )

        # --- 更新：标题 / 状态 / 描述 ---
        patched = client.patch(
            f"{API}/conversations/{conversation_id}",
            headers=owner,
            json={"title": "员工手册咨询", "description": "假期制度", "status": "archived"},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["title"] == "员工手册咨询"
        assert patched.json()["status"] == "archived"
        invalid = client.patch(
            f"{API}/conversations/{conversation_id}",
            headers=owner,
            json={"status": "deleted"},
        )
        assert invalid.status_code == 422

        # --- 消息：写入两条问答，按创建时间升序分页 ---
        base_time = datetime.now(UTC) - timedelta(minutes=5)
        user_message_id = _insert_message(conversation_id, "user", "年假有几天？", base_time)
        assistant_message_id = _insert_message(
            conversation_id,
            "assistant",
            "年假有 5 天 [1]",
            base_time + timedelta(seconds=30),
            parent_message_id=user_message_id,
        )
        messages = client.get(
            f"{API}/conversations/{conversation_id}/messages",
            headers=owner,
            params={"page": 1, "page_size": 1},
        )
        assert messages.status_code == 200, messages.text
        body = messages.json()
        assert body["total"] == 2
        assert len(body["items"]) == 1
        assert body["items"][0]["id"] == str(user_message_id)
        page2 = client.get(
            f"{API}/conversations/{conversation_id}/messages",
            headers=owner,
            params={"page": 2, "page_size": 1},
        ).json()
        assert page2["items"][0]["id"] == str(assistant_message_id)
        assert page2["items"][0]["parent_message_id"] == str(user_message_id)

        # --- 反馈 ---
        feedback = client.patch(
            f"{API}/conversations/{conversation_id}/messages/{assistant_message_id}/feedback",
            headers=owner,
            json={"rating": 5, "feedback": "很有帮助"},
        )
        assert feedback.status_code == 200, feedback.text
        assert feedback.json()["rating"] == 5
        assert feedback.json()["feedback"] == "很有帮助"
        missing = client.patch(
            f"{API}/conversations/{conversation_id}/messages/{uuid4()}/feedback",
            headers=owner,
            json={"rating": 3},
        )
        assert missing.status_code == 404
        assert missing.json()["code"] == "MESSAGE_NOT_FOUND"

        # --- 删除：级联删除消息 ---
        deleted = client.delete(f"{API}/conversations/{conversation_id}", headers=owner)
        assert deleted.status_code == 204, deleted.text
        assert (
            client.get(f"{API}/conversations/{conversation_id}", headers=owner).status_code == 404
        )
        with psycopg.connect(_sync_database_url()) as conn:
            remaining = conn.execute(
                "SELECT count(*) FROM messages WHERE conversation_id = %s",
                (conversation_id,),
            ).fetchone()
        assert remaining is not None and remaining[0] == 0
    finally:
        with psycopg.connect(_sync_database_url()) as conn:
            for conversation_id in conversation_ids:
                conn.execute("DELETE FROM messages WHERE conversation_id = %s", (conversation_id,))
                conn.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
            conn.execute(
                "DELETE FROM conversations WHERE user_id IN (%s, %s)", (owner_id, other_id)
            )
            conn.execute("DELETE FROM users WHERE id IN (%s, %s)", (owner_id, other_id))
            conn.commit()
