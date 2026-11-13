"""知识库集成测试：真实 PostgreSQL 下的权限、上传处理、预览与删除语义。"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.security import get_password_hash
from app.services import embedding_service

API = settings.api_v1_prefix


def _sync_database_url() -> str:
    url = make_url(settings.database_url).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


def _insert_user(user_id: UUID, username: str, email: str, password: str, *, admin: bool) -> None:
    with psycopg.connect(_sync_database_url()) as conn:
        conn.execute(
            """
            INSERT INTO users
                (id, username, email, full_name, hashed_password,
                 is_verified, is_superuser, is_active)
            VALUES (%s, %s, %s, %s, %s, true, %s, true)
            """,
            (user_id, username, email, username, get_password_hash(password), admin),
        )
        conn.commit()


def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post(
        f"{API}/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.integration
def test_knowledge_base_flow(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    upload_dir = tmp_path / "knowledge_bases"
    monkeypatch.setattr(settings, "knowledge_base_upload_dir", str(upload_dir))
    monkeypatch.setattr(settings, "deepseek_api_key", None)

    async def fake_embed_texts(texts: list[str]) -> list[list[float]]:
        return [[0.01] * settings.embedding_dim for _ in texts]

    monkeypatch.setattr(embedding_service, "embed_texts", fake_embed_texts)

    suffix = uuid4().hex[:8]
    password = "Kb-test-123"
    member_id, admin_id = uuid4(), uuid4()
    member_name, admin_name = f"kb_member_{suffix}", f"kb_admin_{suffix}"
    _insert_user(member_id, member_name, f"{member_name}@example.com", password, admin=False)
    _insert_user(admin_id, admin_name, f"{admin_name}@example.com", password, admin=True)

    try:
        member = _login(client, member_name, password)
        admin = _login(client, admin_name, password)

        # --- 创建：普通用户即可 ---
        kb_name = f"制度库-{suffix}"
        created = client.post(
            f"{API}/knowledge-bases",
            headers=member,
            json={
                "name": kb_name,
                "description": "公司制度文档",
                "is_public": False,
                "category": "制度",
                "tags": ["HR", "HR", " "],
            },
        )
        assert created.status_code == 201, created.text
        kb = created.json()
        kb_id = kb["id"]
        assert kb["tags"] == ["HR"]
        assert kb["document_count"] == 0
        assert kb["created_by"] == str(member_id)

        # --- 编辑 / 删除：普通用户被拒绝 ---
        assert (
            client.patch(
                f"{API}/knowledge-bases/{kb_id}",
                headers=member,
                json={"description": "普通用户改名"},
            ).status_code
            == 403
        )
        assert client.delete(f"{API}/knowledge-bases/{kb_id}", headers=member).status_code == 403

        # --- 上传文档：解析 + 切块 + 向量化 ---
        paragraph = "员工每年享有带薪年假，具体天数根据司龄确定。" * 8
        content = "\n\n".join(f"第{index}条 {paragraph}" for index in range(1, 9))
        upload = client.post(
            f"{API}/knowledge-bases/{kb_id}/documents",
            headers=member,
            files={"file": ("员工手册.txt", content.encode(), "text/plain")},
        )
        assert upload.status_code == 201, upload.text
        document = upload.json()
        document_id = document["id"]
        assert document["processing_status"] == "processed", document
        assert document["chunk_count"] >= 1
        assert document["knowledge_base_name"] == kb_name

        stored_path = upload_dir / str(member_id) / document["filename"]
        assert stored_path.exists()

        # --- 原始 / 分块预览 ---
        raw = client.get(f"{API}/documents/{document_id}/content", headers=member)
        assert raw.status_code == 200, raw.text
        assert "带薪年假" in raw.json()["content"]
        assert raw.json()["char_count"] == len(content)

        chunks = client.get(f"{API}/documents/{document_id}/chunks", headers=member)
        assert chunks.status_code == 200, chunks.text
        chunk_body = chunks.json()
        assert chunk_body["total"] == document["chunk_count"]
        assert chunk_body["items"][0]["chunk_index"] == 0
        assert all(item["has_embedding"] for item in chunk_body["items"])

        detail = client.get(f"{API}/knowledge-bases/{kb_id}", headers=member)
        assert detail.json()["document_count"] == 1

        # --- 重复内容与不支持的格式 ---
        duplicate = client.post(
            f"{API}/knowledge-bases/{kb_id}/documents",
            headers=member,
            files={"file": ("copy.txt", content.encode(), "text/plain")},
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["code"] == "DOCUMENT_DUPLICATE"

        unsupported = client.post(
            f"{API}/knowledge-bases/{kb_id}/documents",
            headers=member,
            files={"file": ("virus.zip", b"PK", "application/zip")},
        )
        assert unsupported.status_code == 422
        assert unsupported.json()["code"] == "UNSUPPORTED_DOCUMENT_FORMAT"

        # --- 管理员可以编辑知识库 ---
        renamed = client.patch(
            f"{API}/knowledge-bases/{kb_id}",
            headers=admin,
            json={"name": f"{kb_name}-改", "is_public": True},
        )
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["name"].endswith("-改")
        assert renamed.json()["is_public"] is True

        # --- 删除知识库：文件保留，文档解除关联 ---
        deleted_kb = client.delete(f"{API}/knowledge-bases/{kb_id}", headers=admin)
        assert deleted_kb.status_code == 204, deleted_kb.text
        assert client.get(f"{API}/knowledge-bases/{kb_id}", headers=member).status_code == 404
        assert stored_path.exists()

        unassigned = client.get(
            f"{API}/documents",
            headers=member,
            params={"unassigned": "true", "page_size": 100},
        )
        assert unassigned.status_code == 200, unassigned.text
        orphan_ids = {item["id"] for item in unassigned.json()["items"]}
        assert document_id in orphan_ids

        orphan = client.get(f"{API}/documents/{document_id}", headers=member)
        assert orphan.status_code == 200
        assert orphan.json()["knowledge_base_id"] is None
        assert orphan.json()["knowledge_base_name"] is None

        # --- 删除文档：清理文件、记录与向量块 ---
        deleted_doc = client.delete(f"{API}/documents/{document_id}", headers=member)
        assert deleted_doc.status_code == 204, deleted_doc.text
        assert not stored_path.exists()
        assert client.get(f"{API}/documents/{document_id}", headers=member).status_code == 404
        assert (
            client.get(f"{API}/documents/{document_id}/chunks", headers=member).status_code == 404
        )

        with psycopg.connect(_sync_database_url()) as conn:
            remaining_chunks = conn.execute(
                "SELECT count(*) FROM langchain_pg_embedding WHERE cmetadata->>'document_id' = %s",
                (document_id,),
            ).fetchone()
        assert remaining_chunks is not None and remaining_chunks[0] == 0
    finally:
        with psycopg.connect(_sync_database_url()) as conn:
            conn.execute(
                """
                DELETE FROM langchain_pg_embedding
                WHERE cmetadata->>'document_id' IN
                    (SELECT id::text FROM documents WHERE user_id = %s)
                """,
                (member_id,),
            )
            conn.execute("DELETE FROM documents WHERE user_id = %s", (member_id,))
            conn.execute(
                "DELETE FROM knowledge_bases WHERE created_by IN (%s, %s)",
                (member_id, admin_id),
            )
            conn.execute("DELETE FROM users WHERE id IN (%s, %s)", (member_id, admin_id))
            conn.commit()


@pytest.mark.integration
def test_private_knowledge_base_visibility(client: TestClient) -> None:
    suffix = uuid4().hex[:8]
    password = "Kb-test-123"
    owner_id, other_id = uuid4(), uuid4()
    owner_name, other_name = f"kb_owner_{suffix}", f"kb_other_{suffix}"
    _insert_user(owner_id, owner_name, f"{owner_name}@example.com", password, admin=False)
    _insert_user(other_id, other_name, f"{other_name}@example.com", password, admin=False)

    try:
        owner = _login(client, owner_name, password)
        other = _login(client, other_name, password)

        created = client.post(
            f"{API}/knowledge-bases",
            headers=owner,
            json={"name": f"私有库-{suffix}", "is_public": False},
        )
        assert created.status_code == 201, created.text
        kb_id = created.json()["id"]

        listed = client.get(f"{API}/knowledge-bases", headers=other, params={"page_size": 100})
        assert listed.status_code == 200
        assert all(item["id"] != kb_id for item in listed.json()["items"])
        assert client.get(f"{API}/knowledge-bases/{kb_id}", headers=other).status_code == 403
    finally:
        with psycopg.connect(_sync_database_url()) as conn:
            conn.execute("DELETE FROM knowledge_bases WHERE created_by = %s", (owner_id,))
            conn.execute("DELETE FROM users WHERE id IN (%s, %s)", (owner_id, other_id))
            conn.commit()
