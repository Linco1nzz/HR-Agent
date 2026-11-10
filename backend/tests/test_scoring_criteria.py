"""简历评分标准接口层测试：鉴权、AI 生成、保存与错误映射（不依赖数据库）。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.exceptions import DifyUnavailableError
from app.core.security import create_access_token
from app.db.models import JobDescription, ScoringCriteria
from app.db.session import get_db
from app.main import app
from app.schemas.ai import ChatResponse, WorkflowType
from app.services import dify_service
from tests.fakes import make_user

API = settings.api_v1_prefix


def make_jd_record() -> JobDescription:
    now = datetime.now(UTC)
    return JobDescription(
        id=uuid4(),
        title="高级前端工程师",
        department="产品研发",
        location="上海",
        skills=["Vue 3", "TypeScript"],
        content="# 岗位职责\n负责前端架构与业务开发",
        requirements="有大型中后台项目经验",
        status="published",
        workflow_type="jd_generation",
        created_at=now,
        updated_at=now,
        is_active=True,
    )


def make_criteria_record(jd_id: UUID | None = None) -> ScoringCriteria:
    now = datetime.now(UTC)
    return ScoringCriteria(
        id=uuid4(),
        title="高级前端工程师 - 简历评分标准",
        job_title="高级前端工程师",
        content="# 评分维度\n\n- 专业技能 40 分",
        total_score="100",
        scoring_dimensions=[{"name": "专业技能", "score": 40}],
        status="generated",
        workflow_type="scoring_criteria_generation",
        job_description_id=jd_id,
        created_at=now,
        updated_at=now,
        is_active=True,
    )


class FakeSession:
    """只实现评分标准接口用到的 AsyncSession 子集。"""

    def __init__(self, *, jd: JobDescription | None = None, record: Any = None) -> None:
        self.jd = jd
        self.record = record
        self.user: Any = make_user()
        self.added: ScoringCriteria | None = None
        self.commit_count = 0
        self.refresh_count = 0
        self.now = datetime.now(UTC)

    async def get(self, model: type[Any], record_id: UUID) -> Any:
        if model is JobDescription:
            return self.jd if self.jd is not None and self.jd.id == record_id else None
        if model is ScoringCriteria:
            return self.record if self.record is not None and self.record.id == record_id else None
        return None

    async def scalar(self, statement: Any) -> Any:  # noqa: ARG002 - 鉴权查询固定返回当前用户
        return self.user

    def add(self, record: ScoringCriteria) -> None:
        self.added = record
        record.id = uuid4()
        record.created_at = self.now
        record.updated_at = self.now

    async def commit(self) -> None:
        self.commit_count += 1

    async def refresh(self, record: ScoringCriteria) -> None:
        self.refresh_count += 1


@pytest.fixture()
def criteria_client() -> Iterator[tuple[TestClient, FakeSession]]:
    session = FakeSession(jd=make_jd_record())

    async def _override_get_db() -> AsyncIterator[FakeSession]:
        yield session

    app.dependency_overrides[get_db] = _override_get_db
    # 生成路径在用例中会被 monkeypatch，不需要真实 Dify 客户端；用普通对象
    # 占位可避免 httpx.AsyncClient 在测试结束后未关闭而阻塞退出。
    app.dependency_overrides[dify_service.get_client] = lambda: object()
    try:
        with TestClient(app) as client:
            yield client, session
    finally:
        app.dependency_overrides.clear()


def auth_headers(session: FakeSession) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(session.user.id)}"}


def test_generate_scoring_criteria(
    monkeypatch: pytest.MonkeyPatch,
    criteria_client: tuple[TestClient, FakeSession],
) -> None:
    client, session = criteria_client
    jd = session.jd
    assert jd is not None
    captured: dict[str, Any] = {}

    async def fake_chat(
        request: Any,
        *,
        user_id: UUID | str,
        client: httpx.AsyncClient | None = None,
    ) -> ChatResponse:
        captured["request"] = request
        captured["user_id"] = user_id
        return ChatResponse(
            type=WorkflowType.RESUME_CRITERIA,
            answer="# 评分标准\n\n| 维度 | 分值 |\n| --- | --- |\n| 专业技能 | 40 |",
            conversation_id="conv-2",
            task_id="task-2",
        )

    monkeypatch.setattr(dify_service, "chat", fake_chat)

    response = client.post(
        f"{API}/scoring-criteria/generate",
        headers=auth_headers(session),
        json={"job_description_id": str(jd.id), "total_score": "100"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["content"].startswith("# 评分标准")
    assert body["title"] == "高级前端工程师 - 简历评分标准"
    assert body["job_title"] == "高级前端工程师"
    assert body["job_description_id"] == str(jd.id)
    assert body["conversation_id"] == "conv-2"
    assert body["workflow_type"] == "scoring_criteria_generation"

    request = captured["request"]
    assert request.type == WorkflowType.RESUME_CRITERIA
    assert jd.content in request.query
    assert captured["user_id"] == session.user.id


def test_generate_scoring_criteria_requires_auth(
    criteria_client: tuple[TestClient, FakeSession],
) -> None:
    client, session = criteria_client
    assert session.jd is not None

    response = client.post(
        f"{API}/scoring-criteria/generate",
        json={"job_description_id": str(session.jd.id)},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_TOKEN"


def test_generate_scoring_criteria_requires_existing_jd(
    criteria_client: tuple[TestClient, FakeSession],
) -> None:
    client, session = criteria_client
    session.jd = None

    response = client.post(
        f"{API}/scoring-criteria/generate",
        headers=auth_headers(session),
        json={"job_description_id": str(uuid4())},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_generate_scoring_criteria_stream(
    monkeypatch: pytest.MonkeyPatch,
    criteria_client: tuple[TestClient, FakeSession],
) -> None:
    client, session = criteria_client
    jd = session.jd
    assert jd is not None

    async def fake_events(
        request: Any,
        *,
        user_id: UUID | str,
        client: httpx.AsyncClient | None = None,
    ) -> Any:
        yield {
            "event": "workflow_started",
            "conversation_id": "conv-2",
            "task_id": "task-2",
        }
        yield {"event": "message", "answer": "# 简历评分"}
        yield {"event": "message", "answer": "标准"}
        yield {"event": "message_end", "metadata": {"usage": {"total_tokens": 8}}}

    monkeypatch.setattr(dify_service, "iter_stream_events", fake_events)

    with client.stream(
        "POST",
        f"{API}/scoring-criteria/generate/stream",
        headers=auth_headers(session),
        json={"job_description_id": str(jd.id)},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())

    assert "event: start" in body
    assert "event: delta" in body
    assert '"content": "# 简历评分"' in body
    assert '"content": "标准"' in body
    assert "event: done" in body
    assert '"content": "# 简历评分标准"' in body
    assert '"conversation_id": "conv-2"' in body
    assert '"job_description_id": "' + str(jd.id) + '"' in body


def test_generate_scoring_criteria_maps_dify_error(
    monkeypatch: pytest.MonkeyPatch,
    criteria_client: tuple[TestClient, FakeSession],
) -> None:
    client, session = criteria_client
    assert session.jd is not None

    async def fake_chat(
        request: Any,
        *,
        user_id: UUID | str,
        client: httpx.AsyncClient | None = None,
    ) -> ChatResponse:
        raise DifyUnavailableError("Dify 响应超时")

    monkeypatch.setattr(dify_service, "chat", fake_chat)

    response = client.post(
        f"{API}/scoring-criteria/generate",
        headers=auth_headers(session),
        json={"job_description_id": str(session.jd.id)},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "DIFY_UNAVAILABLE"


def test_create_scoring_criteria(
    criteria_client: tuple[TestClient, FakeSession],
) -> None:
    client, session = criteria_client
    assert session.jd is not None

    response = client.post(
        f"{API}/scoring-criteria",
        headers=auth_headers(session),
        json={
            "title": "前端岗位评分标准",
            "content": "# 评分维度\n\n- 专业技能 40 分",
            "job_description_id": str(session.jd.id),
            "total_score": "100",
            "scoring_dimensions": [{"name": "专业技能", "score": 40}],
            "status": "generated",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["title"] == "前端岗位评分标准"
    assert body["job_title"] == "高级前端工程师"
    assert body["job_description_id"] == str(session.jd.id)
    assert body["created_by"] == str(session.user.id)
    assert session.added is not None
    assert session.commit_count == 1


def test_update_scoring_criteria(
    criteria_client: tuple[TestClient, FakeSession],
) -> None:
    client, session = criteria_client
    record = make_criteria_record()
    session.record = record

    response = client.patch(
        f"{API}/scoring-criteria/{record.id}",
        headers=auth_headers(session),
        json={"title": "前端岗位评分标准（修订）", "status": "published"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "前端岗位评分标准（修订）"
    assert body["status"] == "published"
    assert record.updated_by == session.user.id


def test_get_scoring_criteria_not_found(
    criteria_client: tuple[TestClient, FakeSession],
) -> None:
    client, session = criteria_client

    response = client.get(
        f"{API}/scoring-criteria/{uuid4()}",
        headers=auth_headers(session),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_openapi_documents_scoring_criteria_endpoints(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert f"{API}/scoring-criteria" in paths
    assert f"{API}/scoring-criteria/generate" in paths
    assert f"{API}/scoring-criteria/generate/stream" in paths
    assert f"{API}/scoring-criteria/{{criteria_id}}" in paths
