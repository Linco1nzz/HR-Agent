"""智能面试接口测试：流式生成、保存、列表、详情、导出与鉴权。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import create_access_token
from app.db.models import InterviewPlan
from app.db.session import get_db
from app.main import app
from app.schemas.interview_plan import GenerateInterviewPlanRequest
from app.services import dify_service, interview_plan_service
from app.services.streaming import encode_sse
from tests.fakes import FakeSession, make_user

API = settings.api_v1_prefix


@pytest.fixture()
def interview_client() -> Iterator[tuple[TestClient, FakeSession]]:
    session = FakeSession(make_user())

    async def _override_get_db() -> AsyncIterator[FakeSession]:
        yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[dify_service.get_client] = lambda: httpx.AsyncClient()
    try:
        with TestClient(app) as client:
            yield client, session
    finally:
        app.dependency_overrides.clear()


def auth_headers(session: FakeSession) -> dict[str, str]:
    assert session.user is not None
    return {"Authorization": f"Bearer {create_access_token(session.user.id)}"}


def make_plan_record() -> InterviewPlan:
    now = datetime.now(UTC)
    return InterviewPlan(
        id=uuid4(),
        candidate_name="张三",
        candidate_position="高级前端工程师",
        content="# 张三面试方案\n\n## 一、考察重点\n- 架构能力",
        resume_evaluation_id=uuid4(),
        job_title="高级前端工程师",
        job_description_id=uuid4(),
        conversation_id="conv-4",
        workflow_type="interview_plan",
        created_at=now,
        updated_at=now,
        created_by=uuid4(),
        is_active=True,
    )


def test_stream_generate_interview_plan(
    monkeypatch: pytest.MonkeyPatch,
    interview_client: tuple[TestClient, FakeSession],
) -> None:
    client, session = interview_client
    plan = make_plan_record()
    captured: dict[str, Any] = {}

    async def fake_stream(
        db: Any,
        payload: GenerateInterviewPlanRequest,
        *,
        user_id: UUID | str,
        client: httpx.AsyncClient | None = None,
    ) -> AsyncIterator[bytes]:
        captured["payload"] = payload
        captured["user_id"] = user_id

        async def events() -> AsyncIterator[bytes]:
            yield encode_sse("start", {"workflow_type": "interview_plan"})
            yield encode_sse("delta", {"content": "# 张三面试方案"})
            yield encode_sse(
                "done",
                {
                    "content": plan.content,
                    "candidate_name": plan.candidate_name,
                    "candidate_position": plan.candidate_position,
                    "resume_evaluation_id": str(plan.resume_evaluation_id),
                    "job_title": plan.job_title,
                    "job_description_id": str(plan.job_description_id),
                    "conversation_id": plan.conversation_id,
                    "workflow_type": plan.workflow_type,
                    "task_id": "task-4",
                    "usage": None,
                },
            )

        return events()

    monkeypatch.setattr(interview_plan_service, "stream_generate_interview_plan", fake_stream)

    response = client.post(
        f"{API}/interview-plans/generate/stream",
        headers=auth_headers(session),
        json={
            "resume_evaluation_id": str(plan.resume_evaluation_id),
            "instructions": "重点考察架构能力",
        },
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: start" in response.text
    assert "event: delta" in response.text
    assert "event: done" in response.text
    assert "架构能力" in response.text
    assert captured["payload"].instructions == "重点考察架构能力"
    assert captured["user_id"] == session.user.id  # type: ignore[union-attr]


def test_create_interview_plan(
    monkeypatch: pytest.MonkeyPatch,
    interview_client: tuple[TestClient, FakeSession],
) -> None:
    client, session = interview_client
    plan = make_plan_record()
    captured: dict[str, Any] = {}

    async def fake_create(
        db: Any,
        payload: Any,
        *,
        user_id: UUID,
    ) -> InterviewPlan:
        captured["payload"] = payload
        captured["user_id"] = user_id
        return plan

    monkeypatch.setattr(interview_plan_service, "create_interview_plan", fake_create)

    response = client.post(
        f"{API}/interview-plans",
        headers=auth_headers(session),
        json={
            "candidate_name": "张三",
            "candidate_position": "高级前端工程师",
            "content": plan.content,
            "resume_evaluation_id": str(plan.resume_evaluation_id),
            "conversation_id": "conv-4",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["candidate_name"] == "张三"
    assert body["resume_evaluation_id"] == str(plan.resume_evaluation_id)
    assert body["job_title"] == "高级前端工程师"
    assert captured["user_id"] == session.user.id  # type: ignore[union-attr]


def test_list_interview_plans(
    monkeypatch: pytest.MonkeyPatch,
    interview_client: tuple[TestClient, FakeSession],
) -> None:
    client, session = interview_client
    plan = make_plan_record()
    captured: dict[str, Any] = {}

    async def fake_list(db: Any, **kwargs: Any) -> tuple[list[InterviewPlan], int]:
        captured.update(kwargs)
        return [plan], 1

    monkeypatch.setattr(interview_plan_service, "list_interview_plans", fake_list)

    response = client.get(
        f"{API}/interview-plans",
        headers=auth_headers(session),
        params={"resume_evaluation_id": str(plan.resume_evaluation_id), "keyword": "张三"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["candidate_name"] == "张三"
    assert "架构能力" in body["items"][0]["content_preview"]
    assert captured["resume_evaluation_id"] == plan.resume_evaluation_id
    assert captured["keyword"] == "张三"


def test_get_and_update_interview_plan(
    monkeypatch: pytest.MonkeyPatch,
    interview_client: tuple[TestClient, FakeSession],
) -> None:
    client, session = interview_client
    plan = make_plan_record()

    async def fake_get(db: Any, plan_id: UUID) -> InterviewPlan:
        assert plan_id == plan.id
        return plan

    async def fake_update(
        db: Any,
        plan_id: UUID,
        payload: Any,
        *,
        user_id: UUID,
    ) -> InterviewPlan:
        plan.content = payload.content
        return plan

    monkeypatch.setattr(interview_plan_service, "get_interview_plan", fake_get)
    monkeypatch.setattr(interview_plan_service, "update_interview_plan", fake_update)

    detail = client.get(f"{API}/interview-plans/{plan.id}", headers=auth_headers(session))
    assert detail.status_code == 200, detail.text
    assert detail.json()["content"].startswith("# 张三面试方案")

    updated = client.patch(
        f"{API}/interview-plans/{plan.id}",
        headers=auth_headers(session),
        json={"content": "# 新方案\n- 团队协作"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["content"] == "# 新方案\n- 团队协作"


def test_export_interview_plan_markdown(
    monkeypatch: pytest.MonkeyPatch,
    interview_client: tuple[TestClient, FakeSession],
) -> None:
    client, session = interview_client
    plan = make_plan_record()

    async def fake_get(db: Any, plan_id: UUID) -> InterviewPlan:
        return plan

    monkeypatch.setattr(interview_plan_service, "get_interview_plan", fake_get)

    response = client.get(
        f"{API}/interview-plans/{plan.id}/export",
        headers=auth_headers(session),
        params={"format": "markdown"},
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/markdown")
    assert "attachment;" in response.headers["content-disposition"]
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    assert "# 张三 面试方案" in response.text
    assert "# 张三面试方案" in response.text


def test_export_interview_plan_docx(
    monkeypatch: pytest.MonkeyPatch,
    interview_client: tuple[TestClient, FakeSession],
) -> None:
    client, session = interview_client
    plan = make_plan_record()

    async def fake_get(db: Any, plan_id: UUID) -> InterviewPlan:
        return plan

    monkeypatch.setattr(interview_plan_service, "get_interview_plan", fake_get)

    response = client.get(
        f"{API}/interview-plans/{plan.id}/export",
        headers=auth_headers(session),
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert response.content.startswith(b"PK")


def test_interview_plan_requires_auth(
    interview_client: tuple[TestClient, FakeSession],
) -> None:
    client, _ = interview_client

    response = client.get(f"{API}/interview-plans")

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_TOKEN"


def test_openapi_documents_interview_plan_endpoints(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert f"{API}/interview-plans" in paths
    assert f"{API}/interview-plans/generate/stream" in paths
    assert f"{API}/interview-plans/{{plan_id}}" in paths
    assert f"{API}/interview-plans/{{plan_id}}/export" in paths
