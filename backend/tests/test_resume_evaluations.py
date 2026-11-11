"""简历筛选接口测试：鉴权、上传入参、错误映射与列表 / 详情响应。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.exceptions import ScoringCriteriaRequiredError, UnsupportedResumeFormatError
from app.core.security import create_access_token
from app.db.models import ResumeEvaluation
from app.db.session import get_db
from app.main import app
from app.schemas.resume_evaluation import ResumeStatus
from app.services import dify_service, resume_evaluation_service
from tests.fakes import FakeSession, make_user

API = settings.api_v1_prefix


@pytest.fixture()
def resume_client() -> Iterator[tuple[TestClient, FakeSession]]:
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


def make_resume_record(status: str = "pending") -> ResumeEvaluation:
    now = datetime.now(UTC)
    return ResumeEvaluation(
        id=uuid4(),
        original_filename="张三-前端.txt",
        file_type="txt",
        file_size=128,
        resume_content="张三，5 年前端经验，熟悉 Vue 3。",
        candidate_name="张三",
        candidate_position="高级前端工程师",
        candidate_age=28,
        candidate_gender="男",
        work_years=5.0,
        education_level="本科",
        school="上海理工大学",
        total_score=88.0,
        max_score=100.0,
        evaluation_metrics=[
            {"name": "专业技能", "score": 35, "max": 40, "reason": "Vue 3 经验丰富"},
            {"name": "项目经验", "score": 28, "max": 30, "reason": "有中后台项目经验"},
        ],
        ai_answer='{"total_score": 88}',
        status=status,
        job_title="高级前端工程师",
        job_description_id=uuid4(),
        scoring_criteria_id=uuid4(),
        scoring_criteria_title="高级前端工程师 - 简历评分标准",
        conversation_id="conv-3",
        created_at=now,
        updated_at=now,
        is_active=True,
    )


def test_upload_resume_scores_and_returns_detail(
    monkeypatch: pytest.MonkeyPatch,
    resume_client: tuple[TestClient, FakeSession],
) -> None:
    client, session = resume_client
    record = make_resume_record()
    captured: dict[str, Any] = {}

    async def fake_evaluate(
        db: Any,
        *,
        filename: str,
        content: bytes,
        job_description_id: UUID,
        user_id: UUID,
        client: httpx.AsyncClient,
    ) -> ResumeEvaluation:
        captured.update(
            {
                "db": db,
                "filename": filename,
                "content": content,
                "job_description_id": job_description_id,
                "user_id": user_id,
            }
        )
        return record

    monkeypatch.setattr(resume_evaluation_service, "evaluate_resume", fake_evaluate)

    response = client.post(
        f"{API}/resume-evaluations/upload",
        headers=auth_headers(session),
        data={"job_description_id": str(record.job_description_id)},
        files={"file": ("张三-前端.txt", "张三，5 年前端经验".encode(), "text/plain")},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["candidate_name"] == "张三"
    assert body["total_score"] == 88.0
    assert body["metric_count"] == 2
    assert body["status"] == "pending"
    assert body["resume_content"].startswith("张三")
    assert captured["filename"] == "张三-前端.txt"
    assert captured["content"] == "张三，5 年前端经验".encode()
    assert captured["job_description_id"] == record.job_description_id
    assert captured["user_id"] == session.user.id  # type: ignore[union-attr]


def test_upload_resume_requires_scoring_criteria(
    monkeypatch: pytest.MonkeyPatch,
    resume_client: tuple[TestClient, FakeSession],
) -> None:
    client, session = resume_client
    record = make_resume_record()

    async def fake_evaluate(*args: Any, **kwargs: Any) -> ResumeEvaluation:
        raise ScoringCriteriaRequiredError("先为这个 JD 生成评分标准")

    monkeypatch.setattr(resume_evaluation_service, "evaluate_resume", fake_evaluate)

    response = client.post(
        f"{API}/resume-evaluations/upload",
        headers=auth_headers(session),
        data={"job_description_id": str(record.job_description_id)},
        files={"file": ("resume.txt", b"resume", "text/plain")},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "SCORING_CRITERIA_REQUIRED"


def test_upload_resume_maps_unsupported_format(
    monkeypatch: pytest.MonkeyPatch,
    resume_client: tuple[TestClient, FakeSession],
) -> None:
    client, session = resume_client
    record = make_resume_record()

    async def fake_evaluate(*args: Any, **kwargs: Any) -> ResumeEvaluation:
        raise UnsupportedResumeFormatError()

    monkeypatch.setattr(resume_evaluation_service, "evaluate_resume", fake_evaluate)

    response = client.post(
        f"{API}/resume-evaluations/upload",
        headers=auth_headers(session),
        data={"job_description_id": str(record.job_description_id)},
        files={"file": ("resume.zip", b"zip", "application/zip")},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "UNSUPPORTED_RESUME_FORMAT"


def test_upload_resume_requires_auth(resume_client: tuple[TestClient, FakeSession]) -> None:
    client, _ = resume_client

    response = client.post(
        f"{API}/resume-evaluations/upload",
        data={"job_description_id": str(uuid4())},
        files={"file": ("resume.txt", b"resume", "text/plain")},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_TOKEN"


def test_list_resume_evaluations(
    monkeypatch: pytest.MonkeyPatch,
    resume_client: tuple[TestClient, FakeSession],
) -> None:
    client, session = resume_client
    record = make_resume_record()
    captured: dict[str, Any] = {}

    async def fake_list(db: Any, **kwargs: Any) -> tuple[list[ResumeEvaluation], int]:
        captured.update(kwargs)
        return [record], 1

    monkeypatch.setattr(resume_evaluation_service, "list_resume_evaluations", fake_list)

    response = client.get(
        f"{API}/resume-evaluations",
        headers=auth_headers(session),
        params={"page": 1, "page_size": 10, "keyword": "张三", "status": "pending"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["candidate_name"] == "张三"
    assert body["items"][0]["metric_count"] == 2
    assert captured["keyword"] == "张三"
    assert captured["status"] == ResumeStatus.PENDING


def test_get_resume_evaluation_detail(
    monkeypatch: pytest.MonkeyPatch,
    resume_client: tuple[TestClient, FakeSession],
) -> None:
    client, session = resume_client
    record = make_resume_record()

    async def fake_get(db: Any, evaluation_id: UUID) -> ResumeEvaluation:
        return record

    monkeypatch.setattr(resume_evaluation_service, "get_resume_evaluation", fake_get)

    response = client.get(
        f"{API}/resume-evaluations/{record.id}",
        headers=auth_headers(session),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["resume_content"].startswith("张三")
    assert body["evaluation_metrics"][0]["name"] == "专业技能"
    assert body["candidate_age"] == 28
    assert body["school"] == "上海理工大学"


def test_update_resume_status(
    monkeypatch: pytest.MonkeyPatch,
    resume_client: tuple[TestClient, FakeSession],
) -> None:
    client, session = resume_client
    record = make_resume_record()
    captured: dict[str, Any] = {}

    async def fake_update(
        db: Any,
        evaluation_id: UUID,
        status: ResumeStatus,
        *,
        user_id: UUID,
    ) -> ResumeEvaluation:
        captured["status"] = status
        captured["user_id"] = user_id
        record.status = status.value
        return record

    monkeypatch.setattr(resume_evaluation_service, "update_resume_status", fake_update)

    response = client.patch(
        f"{API}/resume-evaluations/{record.id}/status",
        headers=auth_headers(session),
        json={"status": "interview"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "interview"
    assert captured["status"] == ResumeStatus.INTERVIEW
    assert captured["user_id"] == session.user.id  # type: ignore[union-attr]


def test_openapi_documents_resume_endpoints(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert f"{API}/resume-evaluations" in paths
    assert f"{API}/resume-evaluations/upload" in paths
    assert f"{API}/resume-evaluations/{{evaluation_id}}" in paths
    assert f"{API}/resume-evaluations/{{evaluation_id}}/status" in paths
