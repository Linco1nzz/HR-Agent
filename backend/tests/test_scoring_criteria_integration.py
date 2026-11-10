"""简历评分标准 CRUD 集成测试：连接真实 PostgreSQL，验证模型、迁移与接口链路。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.security import get_password_hash
from app.main import app
from app.schemas.ai import ChatResponse, WorkflowType
from app.services import dify_service

API = settings.api_v1_prefix


def _sync_database_url() -> str:
    url = make_url(settings.database_url).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


@pytest.fixture()
async def dify_stub() -> AsyncIterator[None]:
    """替换 Dify 客户端与 chat 调用，避免集成测试访问真实 LLM。"""

    async def _fake_chat(
        request: object,
        *,
        user_id: UUID | str,
        client: httpx.AsyncClient | None = None,
    ) -> ChatResponse:
        assert getattr(request, "type") == WorkflowType.RESUME_CRITERIA
        return ChatResponse(
            type=WorkflowType.RESUME_CRITERIA,
            answer=(
                "# 简历评分标准\n\n"
                "| 评分维度 | 分值 | 评分要点 |\n"
                "| --- | --- | --- |\n"
                "| 专业技能 | 40 | 前端基础与工程能力 |"
            ),
            conversation_id="criteria-conv-1",
            task_id="criteria-task-1",
        )

    http_client = httpx.AsyncClient()
    original_chat = dify_service.chat
    app.dependency_overrides[dify_service.get_client] = lambda: http_client
    dify_service.chat = _fake_chat  # type: ignore[assignment]
    try:
        yield
    finally:
        dify_service.chat = original_chat  # type: ignore[assignment]
        app.dependency_overrides.pop(dify_service.get_client, None)
        await http_client.aclose()


@pytest.mark.integration
def test_scoring_criteria_crud_flow(client: TestClient, dify_stub: None) -> None:
    user_id = uuid4()
    username = f"criteria_test_{user_id.hex[:8]}"
    email = f"{username}@example.com"
    password = "Criteria-test-123"
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
                (user_id, username, email, "Criteria Test", get_password_hash(password)),
            )
        conn.commit()

    try:
        login = client.post(
            f"{API}/auth/login",
            json={"username": username, "password": password},
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        jd_title = f"高级前端工程师 {user_id.hex[:6]}"
        jd = client.post(
            f"{API}/jds",
            headers=headers,
            json={
                "title": jd_title,
                "department": "产品研发",
                "skills": ["Vue 3", "TypeScript"],
                "content": "# 岗位职责\n负责前端架构与业务开发",
                "requirements": "有大型中后台项目经验",
                "status": "published",
            },
        )
        assert jd.status_code == 201, jd.text
        jd_id = jd.json()["id"]

        generated = client.post(
            f"{API}/scoring-criteria/generate",
            headers=headers,
            json={"job_description_id": jd_id, "total_score": "100"},
        )
        assert generated.status_code == 200, generated.text
        generated_body = generated.json()
        assert generated_body["job_description_id"] == jd_id
        assert generated_body["job_title"] == jd_title
        assert generated_body["content"].startswith("# 简历评分标准")
        assert generated_body["conversation_id"] == "criteria-conv-1"

        saved = client.post(
            f"{API}/scoring-criteria",
            headers=headers,
            json={
                "title": generated_body["title"],
                "job_title": generated_body["job_title"],
                "content": generated_body["content"],
                "total_score": generated_body["total_score"],
                "job_description_id": jd_id,
                "conversation_id": generated_body["conversation_id"],
                "workflow_type": generated_body["workflow_type"],
                "status": "generated",
                "scoring_dimensions": [
                    {"name": "专业技能", "score": 40, "description": "前端基础与工程能力"}
                ],
            },
        )
        assert saved.status_code == 201, saved.text
        saved_body = saved.json()
        criteria_id = saved_body["id"]
        assert saved_body["job_description_id"] == jd_id
        assert saved_body["created_by"] == str(user_id)
        assert saved_body["total_score"] == "100"
        assert saved_body["scoring_dimensions"][0]["name"] == "专业技能"

        listed = client.get(
            f"{API}/scoring-criteria",
            headers=headers,
            params={"job_description_id": jd_id, "keyword": jd_title},
        )
        assert listed.status_code == 200, listed.text
        list_body = listed.json()
        assert list_body["total"] >= 1
        item = next(item for item in list_body["items"] if item["id"] == criteria_id)
        assert "content" not in item
        assert item["job_title"] == jd_title
        assert item["dimension_count"] == 1
        assert item["job_description_id"] == jd_id

        jd_list = client.get(
            f"{API}/jds",
            headers=headers,
            params={"keyword": jd_title},
        )
        assert jd_list.status_code == 200, jd_list.text
        jd_item = next(item for item in jd_list.json()["items"] if item["id"] == jd_id)
        assert jd_item["criteria_count"] == 1

        detail = client.get(f"{API}/scoring-criteria/{criteria_id}", headers=headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["content"].startswith("# 简历评分标准")
        assert detail.json()["conversation_id"] == "criteria-conv-1"
        assert detail.json()["criteria_data"] is None

        updated = client.patch(
            f"{API}/scoring-criteria/{criteria_id}",
            headers=headers,
            json={
                "title": f"{generated_body['title']}（更新）",
                "content": "# 简历评分标准\n\n## 评分维度\n\n- 专业技能 40 分",
                "status": "published",
                "total_score": "120",
                "scoring_dimensions": [{"name": "专业技能", "score": 50}],
            },
        )
        assert updated.status_code == 200, updated.text
        updated_body = updated.json()
        assert updated_body["title"].endswith("（更新）")
        assert updated_body["status"] == "published"
        assert updated_body["total_score"] == "120"
        assert updated_body["scoring_dimensions"] == [{"name": "专业技能", "score": 50}]

        missing = client.get(f"{API}/scoring-criteria/{uuid4()}", headers=headers)
        assert missing.status_code == 404
        assert missing.json()["code"] == "NOT_FOUND"

        missing_jd = client.post(
            f"{API}/scoring-criteria/generate",
            headers=headers,
            json={"job_description_id": str(uuid4())},
        )
        assert missing_jd.status_code == 404
        assert missing_jd.json()["code"] == "NOT_FOUND"
    finally:
        with psycopg.connect(db_url) as conn:
            conn.execute("DELETE FROM scoring_criteria WHERE created_by = %s", (user_id,))
            conn.execute("DELETE FROM job_description WHERE created_by = %s", (user_id,))
            conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
            conn.commit()
