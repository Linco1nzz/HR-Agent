"""JD CRUD 集成测试：连接真实 PostgreSQL，验证模型、迁移与接口链路。"""

from __future__ import annotations

from uuid import uuid4

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


@pytest.mark.integration
def test_jd_crud_flow(client: TestClient) -> None:
    user_id = uuid4()
    username = f"jd_test_{user_id.hex[:8]}"
    email = f"{username}@example.com"
    password = "Jd-test-123"
    db_url = _sync_database_url()

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users
                    (id, username, email, full_name, hashed_password,
                     is_verified, is_superuser, is_active)
                VALUES (%s, %s, %s, %s, %s, true, false, true)
                """,
                (user_id, username, email, "JD Test", get_password_hash(password)),
            )
        conn.commit()

    try:
        login = client.post(
            f"{API}/auth/login",
            json={"username": username, "password": password},
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        title = f"高级前端工程师 {user_id.hex[:6]}"
        payload = {
            "title": title,
            "department": "产品研发",
            "location": "上海",
            "salary_range": "25-40K",
            "experience_level": "3-5 年",
            "education": "本科",
            "job_type": "全职",
            "skills": ["Vue 3", "TypeScript"],
            "content": "# 岗位职责\n负责前端开发\n\n# 任职要求\n熟悉 Vue 3",
            "requirements": "有大型中后台项目经验",
            "status": "generated",
            "conversation_id": "conv-1",
        }

        created = client.post(f"{API}/jds", headers=headers, json=payload)
        assert created.status_code == 201, created.text
        created_body = created.json()
        jd_id = created_body["id"]
        assert created_body["title"] == title
        assert created_body["created_by"] == str(user_id)
        assert created_body["skills"] == ["Vue 3", "TypeScript"]

        listed = client.get(f"{API}/jds", headers=headers, params={"keyword": title})
        assert listed.status_code == 200, listed.text
        list_body = listed.json()
        assert list_body["total"] >= 1
        item = next(item for item in list_body["items"] if item["id"] == jd_id)
        assert "content" not in item
        assert item["content_preview"].startswith("岗位职责")

        detail = client.get(f"{API}/jds/{jd_id}", headers=headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["content"].startswith("# 岗位职责")
        assert detail.json()["conversation_id"] == "conv-1"

        updated = client.patch(
            f"{API}/jds/{jd_id}",
            headers=headers,
            json={
                "title": f"{title}（更新）",
                "content": "# 岗位职责\n负责前端架构",
                "status": "published",
                "skills": ["Vue 3"],
            },
        )
        assert updated.status_code == 200, updated.text
        updated_body = updated.json()
        assert updated_body["title"].endswith("（更新）")
        assert updated_body["status"] == "published"
        assert updated_body["content"] == "# 岗位职责\n负责前端架构"
        assert updated_body["skills"] == ["Vue 3"]

        missing = client.get(f"{API}/jds/{uuid4()}", headers=headers)
        assert missing.status_code == 404
        assert missing.json()["code"] == "NOT_FOUND"
    finally:
        with psycopg.connect(db_url) as conn:
            conn.execute("DELETE FROM job_description WHERE created_by = %s", (user_id,))
            conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
            conn.commit()
