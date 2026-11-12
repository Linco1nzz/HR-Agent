"""智能面试集成测试：真实 PostgreSQL 下的流式生成、保存、编辑与导出。"""

from __future__ import annotations

import json
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
from app.schemas.ai import WorkflowType
from app.services import dify_service

API = settings.api_v1_prefix


def _sync_database_url() -> str:
    url = make_url(settings.database_url).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


@pytest.fixture()
async def interview_dify_stub() -> AsyncIterator[None]:
    """替换 Dify 流式事件，返回固定的面试方案。"""

    async def _fake_iter_events(
        request: object,
        *,
        user_id: UUID | str,
        client: httpx.AsyncClient | None = None,
    ) -> AsyncIterator[dict[str, object]]:
        assert getattr(request, "type") == WorkflowType.INTERVIEW_PLAN
        yield {"event": "message", "answer": "# 张三面试方案\n\n## 一、考察重点\n"}
        yield {"event": "message", "answer": "- 架构能力\n- 团队协作"}
        yield {
            "event": "message_end",
            "conversation_id": "interview-conv-1",
            "task_id": "interview-task-1",
            "metadata": {"usage": {"total_tokens": 66}},
        }
        yield {"event": "workflow_finished", "data": {"outputs": {}}}

    http_client = httpx.AsyncClient()
    original = dify_service.iter_stream_events
    app.dependency_overrides[dify_service.get_client] = lambda: http_client
    dify_service.iter_stream_events = _fake_iter_events  # type: ignore[assignment]
    try:
        yield
    finally:
        dify_service.iter_stream_events = original  # type: ignore[assignment]
        app.dependency_overrides.pop(dify_service.get_client, None)
        await http_client.aclose()


def _done_payload(response_text: str) -> dict[str, object]:
    for frame in response_text.split("\n\n"):
        if frame.startswith("event: done"):
            return json.loads(frame.split("data: ", 1)[1])
    raise AssertionError(f"未找到 done 事件：{response_text}")


@pytest.mark.integration
def test_interview_plan_flow(
    client: TestClient,
    interview_dify_stub: None,
) -> None:
    user_id = uuid4()
    username = f"interview_test_{user_id.hex[:8]}"
    email = f"{username}@example.com"
    password = "Interview-test-123"
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
                (user_id, username, email, "Interview Test", get_password_hash(password)),
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
                "requirements": "有大型中后台项目经验",
                "status": "published",
            },
        )
        assert jd.status_code == 201, jd.text
        jd_id = jd.json()["id"]

        resume_id = uuid4()
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO resume_evaluation
                        (id, original_filename, file_type, file_size, resume_content,
                         candidate_name, candidate_position, total_score, max_score,
                         status, job_title, job_description_id, scoring_criteria_id,
                         created_by, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, true)
                    """,
                    (
                        resume_id,
                        "张三-前端.txt",
                        "txt",
                        128,
                        "张三，5 年前端经验，熟悉 Vue 3 和 TypeScript。",
                        "张三",
                        "高级前端工程师",
                        88.0,
                        100.0,
                        "pending",
                        jd_title,
                        jd_id,
                        uuid4(),
                        user_id,
                    ),
                )
            conn.commit()

        empty = client.get(
            f"{API}/interview-plans",
            headers=headers,
            params={"resume_evaluation_id": str(resume_id)},
        )
        assert empty.status_code == 200, empty.text
        assert empty.json()["total"] == 0

        generated = client.post(
            f"{API}/interview-plans/generate/stream",
            headers=headers,
            json={
                "resume_evaluation_id": str(resume_id),
                "instructions": "重点考察架构能力",
            },
        )
        assert generated.status_code == 200, generated.text
        assert generated.headers["content-type"].startswith("text/event-stream")
        assert "event: delta" in generated.text
        done = _done_payload(generated.text)
        assert done["candidate_name"] == "张三"
        assert done["candidate_position"] == "高级前端工程师"
        assert done["resume_evaluation_id"] == str(resume_id)
        assert done["job_title"] == jd_title
        assert done["job_description_id"] == jd_id
        assert "架构能力" in done["content"]

        created = client.post(
            f"{API}/interview-plans",
            headers=headers,
            json={
                "candidate_name": done["candidate_name"],
                "candidate_position": done["candidate_position"],
                "content": done["content"],
                "resume_evaluation_id": str(resume_id),
                "conversation_id": done["conversation_id"],
            },
        )
        assert created.status_code == 201, created.text
        plan = created.json()
        plan_id = plan["id"]
        assert plan["job_title"] == jd_title
        assert plan["job_description_id"] == jd_id

        listed = client.get(
            f"{API}/interview-plans",
            headers=headers,
            params={"resume_evaluation_id": str(resume_id)},
        )
        assert listed.status_code == 200, listed.text
        assert listed.json()["total"] == 1
        assert listed.json()["items"][0]["id"] == plan_id

        detail = client.get(f"{API}/interview-plans/{plan_id}", headers=headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["content"].startswith("# 张三面试方案")

        updated = client.patch(
            f"{API}/interview-plans/{plan_id}",
            headers=headers,
            json={"content": "# 更新后的面试方案\n- 团队协作"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["content"].startswith("# 更新后的面试方案")

        exported_md = client.get(
            f"{API}/interview-plans/{plan_id}/export",
            headers=headers,
            params={"format": "markdown"},
        )
        assert exported_md.status_code == 200, exported_md.text
        assert "# 张三 面试方案" in exported_md.text
        assert "更新后的面试方案" in exported_md.text

        exported_docx = client.get(
            f"{API}/interview-plans/{plan_id}/export",
            headers=headers,
        )
        assert exported_docx.status_code == 200, exported_docx.text
        assert exported_docx.content.startswith(b"PK")
    finally:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM interview_plan WHERE created_by = %s", (user_id,))
                cur.execute("DELETE FROM resume_evaluation WHERE created_by = %s", (user_id,))
                cur.execute("DELETE FROM job_description WHERE created_by = %s", (user_id,))
                cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
            conn.commit()
