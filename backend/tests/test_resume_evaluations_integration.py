"""简历筛选集成测试：真实 PostgreSQL 下的上传评分、列表、详情与状态更新。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.security import get_password_hash
from app.main import app
from app.schemas.ai import ChatResponse, ChatUsage, WorkflowType
from app.services import dify_service

API = settings.api_v1_prefix


def _sync_database_url() -> str:
    url = make_url(settings.database_url).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


@pytest.fixture()
async def resume_dify_stub() -> AsyncIterator[None]:
    """替换 Dify 客户端与 chat 调用，返回固定 JSON 评分。"""

    async def _fake_chat(
        request: object,
        *,
        user_id: UUID | str,
        client: httpx.AsyncClient | None = None,
    ) -> ChatResponse:
        assert getattr(request, "type") == WorkflowType.RESUME_EVALUATION
        return ChatResponse(
            type=WorkflowType.RESUME_EVALUATION,
            answer=(
                '{"evaluation_metrics": ['
                '{"name": "专业技能", "score": 35, "max": 40, "reason": "Vue 3 经验丰富"},'
                '{"name": "项目经验", "score": 28, "max": 30, "reason": "中后台项目经验"}'
                "],"
                '"total_score": 88, "name": "张三", "position": "高级前端工程师",'
                '"workYears": "5年", "education": "本科", "age": 28, "sex": "男",'
                '"school": "上海理工大学"}'
            ),
            conversation_id="resume-conv-1",
            task_id="resume-task-1",
            usage=ChatUsage(total_tokens=128),
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
def test_resume_screening_flow(
    client: TestClient,
    resume_dify_stub: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_id = uuid4()
    username = f"resume_test_{user_id.hex[:8]}"
    email = f"{username}@example.com"
    password = "Resume-test-123"
    db_url = _sync_database_url()
    monkeypatch.setattr(settings, "resume_upload_dir", str(tmp_path))

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users
                    (id, username, email, full_name, hashed_password,
                     is_verified, is_superuser, is_active)
                VALUES (%s, %s, %s, %s, %s, true, false, true)
                """,
                (user_id, username, email, "Resume Test", get_password_hash(password)),
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
                "content": "# 岗位职责\n负责前端架构与业务开发",
                "status": "published",
            },
        )
        assert jd.status_code == 201, jd.text
        jd_id = jd.json()["id"]

        criteria = client.post(
            f"{API}/scoring-criteria",
            headers=headers,
            json={
                "title": f"{jd_title} - 评分标准",
                "job_title": jd_title,
                "content": "# 评分标准\n- 专业技能 40 分\n- 项目经验 30 分",
                "total_score": "100",
                "job_description_id": jd_id,
                "status": "generated",
            },
        )
        assert criteria.status_code == 201, criteria.text

        upload = client.post(
            f"{API}/resume-evaluations/upload",
            headers=headers,
            data={"job_description_id": jd_id},
            files={"file": ("张三-前端.txt", "张三，5 年前端经验。".encode(), "text/plain")},
        )
        assert upload.status_code == 201, upload.text
        body = upload.json()
        resume_id = body["id"]
        assert body["candidate_name"] == "张三"
        assert body["total_score"] == 88.0
        assert body["max_score"] == 100.0
        assert body["status"] == "pending"
        assert body["metric_count"] == 2
        assert body["job_description_id"] == jd_id
        assert body["scoring_criteria_id"] == criteria.json()["id"]
        assert body["resume_content"].startswith("张三")
        assert body["evaluation_metrics"][0]["name"] == "专业技能"
        assert body["ai_answer"]

        listed = client.get(
            f"{API}/resume-evaluations",
            headers=headers,
            params={"job_description_id": jd_id, "keyword": "张三"},
        )
        assert listed.status_code == 200, listed.text
        assert listed.json()["total"] == 1
        assert listed.json()["items"][0]["id"] == resume_id

        detail = client.get(f"{API}/resume-evaluations/{resume_id}", headers=headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["resume_content"].startswith("张三")

        updated = client.patch(
            f"{API}/resume-evaluations/{resume_id}/status",
            headers=headers,
            json={"status": "interview"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["status"] == "interview"

        no_criteria_jd = client.post(
            f"{API}/jds",
            headers=headers,
            json={"title": f"无评分标准岗位 {user_id.hex[:6]}", "content": "# JD"},
        )
        assert no_criteria_jd.status_code == 201, no_criteria_jd.text
        rejected = client.post(
            f"{API}/resume-evaluations/upload",
            headers=headers,
            data={"job_description_id": no_criteria_jd.json()["id"]},
            files={"file": ("李四.txt", "李四，3 年经验。".encode(), "text/plain")},
        )
        assert rejected.status_code == 422, rejected.text
        assert rejected.json()["code"] == "SCORING_CRITERIA_REQUIRED"
    finally:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT file_path FROM resume_evaluation WHERE created_by = %s",
                    (user_id,),
                )
                for (file_path,) in cur.fetchall():
                    if file_path:
                        Path(file_path).unlink(missing_ok=True)
                cur.execute("DELETE FROM resume_evaluation WHERE created_by = %s", (user_id,))
                cur.execute("DELETE FROM scoring_criteria WHERE created_by = %s", (user_id,))
                cur.execute("DELETE FROM job_description WHERE created_by = %s", (user_id,))
                cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
            conn.commit()
