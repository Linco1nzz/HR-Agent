"""简历评分标准服务层测试：JD 查询组装、Dify 调用、落库与列表摘要。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from app.core.exceptions import DifyInvalidResponseError, NotFoundError, WorkflowValidationError
from app.db.models import JobDescription, ScoringCriteria
from app.schemas.ai import ChatResponse, ChatUsage, WorkflowType
from app.schemas.scoring_criteria import (
    GenerateScoringCriteriaRequest,
    ScoringCriteriaCreate,
    ScoringCriteriaStatus,
    ScoringCriteriaUpdate,
)
from app.services import dify_service, scoring_criteria_service


def make_jd_record(**overrides: Any) -> JobDescription:
    now = datetime.now(UTC)
    data: dict[str, Any] = {
        "id": uuid4(),
        "title": "高级前端工程师",
        "department": "产品研发",
        "location": "上海",
        "experience_level": "3-5 年",
        "education": "本科",
        "skills": ["Vue 3", "TypeScript"],
        "content": "# 岗位职责\n负责前端架构与业务开发",
        "requirements": "有大型中后台项目经验",
        "status": "published",
        "workflow_type": "jd_generation",
        "created_at": now,
        "updated_at": now,
        "is_active": True,
    }
    data.update(overrides)
    return JobDescription(**data)


def make_criteria_record(**overrides: Any) -> ScoringCriteria:
    now = datetime.now(UTC)
    data: dict[str, Any] = {
        "id": uuid4(),
        "title": "高级前端工程师 - 简历评分标准",
        "job_title": "高级前端工程师",
        "content": "# 评分维度\n\n- 专业技能 40 分\n- 项目经验 30 分",
        "criteria_data": {"source": "ai"},
        "total_score": "100",
        "scoring_dimensions": [
            {"name": "专业技能", "score": 40},
            {"name": "项目经验", "score": 30},
        ],
        "status": "generated",
        "workflow_type": "scoring_criteria_generation",
        "job_description_id": uuid4(),
        "created_at": now,
        "updated_at": now,
        "is_active": True,
    }
    data.update(overrides)
    return ScoringCriteria(**data)


class FakeSession:
    """只实现评分标准服务用到的 AsyncSession 子集。"""

    def __init__(self, *, jd: JobDescription | None = None, record: Any = None) -> None:
        self.jd = jd
        self.record = record
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

    def add(self, record: ScoringCriteria) -> None:
        self.added = record
        record.id = uuid4()
        record.created_at = self.now
        record.updated_at = self.now

    async def commit(self) -> None:
        self.commit_count += 1

    async def refresh(self, record: ScoringCriteria) -> None:
        self.refresh_count += 1


def make_generate_payload(**overrides: Any) -> GenerateScoringCriteriaRequest:
    data: dict[str, Any] = {
        "job_description_id": uuid4(),
        "total_score": "100",
        "instructions": "重点关注前端工程化经验",
    }
    data.update(overrides)
    return GenerateScoringCriteriaRequest(**data)


# ---------------------------------------------------------------------------
# 查询组装与 Dify 调用
# ---------------------------------------------------------------------------
def test_build_generation_query_contains_jd_fields() -> None:
    jd = make_jd_record()

    query = scoring_criteria_service.build_generation_query(
        jd,
        total_score="100",
        instructions="重点关注前端工程化经验",
    )

    assert "100 分制" in query
    assert "至少包含 4 个评分维度" in query
    assert "高级前端工程师" in query
    assert "产品研发" in query
    assert "上海" in query
    assert "3-5 年" in query
    assert "本科" in query
    assert "Vue 3、TypeScript" in query
    assert jd.content in query
    assert jd.requirements in query
    assert "重点关注前端工程化经验" in query
    assert "Markdown" in query


async def test_generate_scoring_criteria_calls_dify_type2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jd = make_jd_record()
    payload = make_generate_payload(job_description_id=jd.id)
    db = FakeSession(jd=jd)
    captured: dict[str, Any] = {}

    async def fake_chat(
        request: Any,
        *,
        user_id: UUID | str,
        client: httpx.AsyncClient | None = None,
    ) -> ChatResponse:
        captured["request"] = request
        captured["user_id"] = user_id
        captured["client"] = client
        return ChatResponse(
            type=WorkflowType.RESUME_CRITERIA,
            answer="# 评分标准\n\n| 维度 | 分值 |\n| --- | --- |\n| 专业技能 | 40 |",
            conversation_id="conv-2",
            task_id="task-2",
            usage=ChatUsage(total_tokens=64),
        )

    monkeypatch.setattr(dify_service, "chat", fake_chat)
    user_id = uuid4()

    result = await scoring_criteria_service.generate_scoring_criteria(
        db,  # type: ignore[arg-type]
        payload,
        user_id=user_id,
    )

    assert result.content.startswith("# 评分标准")
    assert result.title == "高级前端工程师 - 简历评分标准"
    assert result.job_title == "高级前端工程师"
    assert result.job_description_id == jd.id
    assert result.conversation_id == "conv-2"
    assert result.task_id == "task-2"
    assert result.workflow_type == "scoring_criteria_generation"
    assert result.total_score == "100"
    assert result.usage is not None and result.usage.total_tokens == 64

    request = captured["request"]
    assert request.type == WorkflowType.RESUME_CRITERIA
    assert jd.content in request.query
    assert "重点关注前端工程化经验" in request.query
    assert request.inputs == {}
    assert captured["user_id"] == user_id


async def test_generate_scoring_criteria_uses_custom_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jd = make_jd_record()
    payload = make_generate_payload(job_description_id=jd.id, title="  前端岗位评分表  ")

    async def fake_chat(
        request: Any,
        *,
        user_id: UUID | str,
        client: httpx.AsyncClient | None = None,
    ) -> ChatResponse:
        return ChatResponse(type=WorkflowType.RESUME_CRITERIA, answer="# 评分标准")

    monkeypatch.setattr(dify_service, "chat", fake_chat)

    result = await scoring_criteria_service.generate_scoring_criteria(
        FakeSession(jd=jd),  # type: ignore[arg-type]
        payload,
        user_id=uuid4(),
    )

    assert result.title == "前端岗位评分表"


async def test_generate_scoring_criteria_truncates_default_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jd = make_jd_record(title="前" * 255)
    payload = make_generate_payload(job_description_id=jd.id)

    async def fake_chat(
        request: Any,
        *,
        user_id: UUID | str,
        client: httpx.AsyncClient | None = None,
    ) -> ChatResponse:
        return ChatResponse(type=WorkflowType.RESUME_CRITERIA, answer="# 评分标准")

    monkeypatch.setattr(dify_service, "chat", fake_chat)

    result = await scoring_criteria_service.generate_scoring_criteria(
        FakeSession(jd=jd),  # type: ignore[arg-type]
        payload,
        user_id=uuid4(),
    )

    assert len(result.title) == 255


async def test_generate_scoring_criteria_requires_existing_jd() -> None:
    payload = make_generate_payload()

    with pytest.raises(NotFoundError):
        await scoring_criteria_service.generate_scoring_criteria(
            FakeSession(),  # type: ignore[arg-type]
            payload,
            user_id=uuid4(),
        )


async def test_generate_scoring_criteria_rejects_empty_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jd = make_jd_record()

    async def fake_chat(
        request: Any,
        *,
        user_id: UUID | str,
        client: httpx.AsyncClient | None = None,
    ) -> ChatResponse:
        return ChatResponse(type=WorkflowType.RESUME_CRITERIA, answer="   ")

    monkeypatch.setattr(dify_service, "chat", fake_chat)

    with pytest.raises(DifyInvalidResponseError):
        await scoring_criteria_service.generate_scoring_criteria(
            FakeSession(jd=jd),  # type: ignore[arg-type]
            make_generate_payload(job_description_id=jd.id),
            user_id=uuid4(),
        )


# ---------------------------------------------------------------------------
# 落库
# ---------------------------------------------------------------------------
async def test_create_scoring_criteria_fills_job_title_from_jd() -> None:
    jd = make_jd_record()
    db = FakeSession(jd=jd)
    user_id = uuid4()

    record = await scoring_criteria_service.create_scoring_criteria(
        db,  # type: ignore[arg-type]
        ScoringCriteriaCreate(
            title="前端岗位评分标准",
            content="# 评分维度\n\n- 专业技能 40 分",
            job_description_id=jd.id,
            status=ScoringCriteriaStatus.GENERATED,
        ),
        user_id=user_id,
    )

    assert db.added is record
    assert record.job_title == jd.title
    assert record.created_by == user_id
    assert db.commit_count == 1
    assert db.refresh_count == 1


async def test_create_scoring_criteria_requires_existing_jd() -> None:
    db = FakeSession()

    with pytest.raises(NotFoundError):
        await scoring_criteria_service.create_scoring_criteria(
            db,  # type: ignore[arg-type]
            ScoringCriteriaCreate(
                title="前端岗位评分标准",
                content="# 评分维度",
                job_description_id=uuid4(),
            ),
            user_id=uuid4(),
        )


async def test_update_scoring_criteria_applies_explicit_fields() -> None:
    record = make_criteria_record()
    db = FakeSession(record=record)
    user_id = uuid4()

    updated = await scoring_criteria_service.update_scoring_criteria(
        db,  # type: ignore[arg-type]
        record.id,
        ScoringCriteriaUpdate(
            title="前端岗位评分标准（修订）",
            total_score="120",
            status=ScoringCriteriaStatus.PUBLISHED,
            scoring_dimensions=[{"name": "专业技能", "score": 50}],
        ),
        user_id=user_id,
    )

    assert updated.title == "前端岗位评分标准（修订）"
    assert updated.total_score == "120"
    assert updated.status == ScoringCriteriaStatus.PUBLISHED
    assert updated.scoring_dimensions == [{"name": "专业技能", "score": 50}]
    assert updated.updated_by == user_id
    assert db.commit_count == 1


async def test_update_scoring_criteria_rejects_null_content() -> None:
    record = make_criteria_record()
    db = FakeSession(record=record)

    with pytest.raises(WorkflowValidationError):
        await scoring_criteria_service.update_scoring_criteria(
            db,  # type: ignore[arg-type]
            record.id,
            ScoringCriteriaUpdate(content=None),
            user_id=uuid4(),
        )


def test_to_list_item_builds_preview_and_dimension_count() -> None:
    record = make_criteria_record(content="第一行\n\n第二行 " + "内容" * 200)

    item = scoring_criteria_service.to_list_item(record)

    assert item.id == record.id
    assert item.title == record.title
    assert item.job_title == record.job_title
    assert item.total_score == "100"
    assert item.status == ScoringCriteriaStatus.GENERATED
    assert item.job_description_id == record.job_description_id
    assert item.dimension_count == 2
    assert "第一行 第二行" in item.content_preview
    assert item.content_preview.endswith("…")
    assert len(item.content_preview) <= 141


# ---------------------------------------------------------------------------
# 流式生成
# ---------------------------------------------------------------------------
def _parse_sse_frames(chunks: list[bytes]) -> list[tuple[str, dict[str, Any]]]:
    frames: list[tuple[str, dict[str, Any]]] = []
    for raw in b"".join(chunks).decode().split("\n\n"):
        if not raw.strip():
            continue
        event = "message"
        data_lines: list[str] = []
        for line in raw.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if data_lines:
            frames.append((event, json.loads("\n".join(data_lines))))
    return frames


async def test_stream_generate_scoring_criteria_emits_delta_and_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jd = make_jd_record()
    payload = make_generate_payload(job_description_id=jd.id)

    async def fake_events(
        request: Any,
        *,
        user_id: UUID | str,
        client: httpx.AsyncClient | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        yield {
            "event": "workflow_started",
            "conversation_id": "conv-2",
            "task_id": "task-2",
        }
        yield {"event": "message", "answer": "# 简历评分"}
        yield {"event": "message", "answer": "标准"}
        yield {"event": "message_end", "metadata": {"usage": {"total_tokens": 24}}}
        yield {
            "event": "workflow_finished",
            "data": {"outputs": {"answer": "# 简历评分标准"}},
        }

    monkeypatch.setattr(dify_service, "iter_stream_events", fake_events)
    client = httpx.AsyncClient()
    try:
        iterator = await scoring_criteria_service.stream_generate_scoring_criteria(
            FakeSession(jd=jd),  # type: ignore[arg-type]
            payload,
            user_id="u-1",
            client=client,
        )
        chunks = [chunk async for chunk in iterator]
    finally:
        await client.aclose()

    frames = _parse_sse_frames(chunks)
    assert [event for event, _ in frames] == ["start", "delta", "delta", "done"]
    assert "".join(data["content"] for event, data in frames if event == "delta") == (
        "# 简历评分标准"
    )

    done = frames[-1][1]
    assert done["content"] == "# 简历评分标准"
    assert done["title"] == "高级前端工程师 - 简历评分标准"
    assert done["job_title"] == "高级前端工程师"
    assert done["job_description_id"] == str(jd.id)
    assert done["conversation_id"] == "conv-2"
    assert done["task_id"] == "task-2"
    assert done["usage"]["total_tokens"] == 24
    assert done["workflow_type"] == "scoring_criteria_generation"


async def test_stream_generate_scoring_criteria_handles_dify_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jd = make_jd_record()
    payload = make_generate_payload(job_description_id=jd.id)

    async def fake_events(
        request: Any,
        *,
        user_id: UUID | str,
        client: httpx.AsyncClient | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        yield {
            "event": "error",
            "status": 400,
            "code": "DIFY_INVALID_PARAM",
            "message": "bad inputs",
        }

    monkeypatch.setattr(dify_service, "iter_stream_events", fake_events)
    client = httpx.AsyncClient()
    try:
        iterator = await scoring_criteria_service.stream_generate_scoring_criteria(
            FakeSession(jd=jd),  # type: ignore[arg-type]
            payload,
            user_id="u-1",
            client=client,
        )
        chunks = [chunk async for chunk in iterator]
    finally:
        await client.aclose()

    frames = _parse_sse_frames(chunks)
    assert frames[-1][0] == "error"
    assert frames[-1][1]["code"] == "DIFY_INVALID_PARAM"
    assert frames[-1][1]["status"] == 400


async def test_stream_generate_scoring_criteria_rejects_empty_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jd = make_jd_record()
    payload = make_generate_payload(job_description_id=jd.id)

    async def fake_events(
        request: Any,
        *,
        user_id: UUID | str,
        client: httpx.AsyncClient | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        yield {"event": "message_end"}

    monkeypatch.setattr(dify_service, "iter_stream_events", fake_events)
    client = httpx.AsyncClient()
    try:
        iterator = await scoring_criteria_service.stream_generate_scoring_criteria(
            FakeSession(jd=jd),  # type: ignore[arg-type]
            payload,
            user_id="u-1",
            client=client,
        )
        chunks = [chunk async for chunk in iterator]
    finally:
        await client.aclose()

    frames = _parse_sse_frames(chunks)
    assert frames[-1][0] == "error"
    assert frames[-1][1]["code"] == "DIFY_INVALID_RESPONSE"


async def test_stream_generate_scoring_criteria_requires_existing_jd() -> None:
    payload = make_generate_payload()

    with pytest.raises(NotFoundError):
        await scoring_criteria_service.stream_generate_scoring_criteria(
            FakeSession(),  # type: ignore[arg-type]
            payload,
            user_id="u-1",
        )
