"""JD 服务层单元测试：生成查询组装、Dify 调用、摘要与更新校验。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from app.core.exceptions import DifyInvalidResponseError, WorkflowValidationError
from app.db.models import JobDescription
from app.schemas.ai import ChatResponse, ChatUsage, WorkflowType
from app.schemas.jd import (
    GenerateJDRequest,
    JDStatus,
    JobDescriptionCreate,
    JobDescriptionUpdate,
)
from app.services import dify_service, jd_service


def make_generate_payload(**overrides: Any) -> GenerateJDRequest:
    data: dict[str, Any] = {
        "title": "高级前端工程师",
        "department": "产品研发",
        "location": "上海",
        "salary_range": "25-40K",
        "experience_level": "3-5 年",
        "education": "本科",
        "job_type": "全职",
        "skills": ["Vue 3", "TypeScript"],
        "requirements": "有大型中后台项目经验",
    }
    data.update(overrides)
    return GenerateJDRequest(**data)


def make_jd_record(**overrides: Any) -> JobDescription:
    now = datetime.now(UTC)
    data: dict[str, Any] = {
        "id": uuid4(),
        "title": "高级前端工程师",
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
        "workflow_type": "jd_generation",
        "created_at": now,
        "updated_at": now,
        "is_active": True,
    }
    data.update(overrides)
    return JobDescription(**data)


class FakeWriteSession:
    """只实现 create / update 路径用到的 AsyncSession 子集。"""

    def __init__(self, record: JobDescription | None = None) -> None:
        self.record = record
        self.added: JobDescription | None = None
        self.commit_count = 0
        self.refresh_count = 0
        self.now = datetime.now(UTC)

    async def get(self, model: type[JobDescription], record_id: UUID) -> JobDescription | None:
        return self.record

    def add(self, record: JobDescription) -> None:
        self.added = record
        record.id = uuid4()
        record.created_at = self.now
        record.updated_at = self.now

    async def commit(self) -> None:
        self.commit_count += 1

    async def refresh(self, record: JobDescription) -> None:
        self.refresh_count += 1


# ---------------------------------------------------------------------------
# 生成查询与 Dify 调用
# ---------------------------------------------------------------------------
def test_build_generation_query_contains_form_fields() -> None:
    query = jd_service.build_generation_query(make_generate_payload())

    assert "高级前端工程师" in query
    assert "产品研发" in query
    assert "上海" in query
    assert "25-40K" in query
    assert "3-5 年" in query
    assert "本科" in query
    assert "全职" in query
    assert "Vue 3、TypeScript" in query
    assert "有大型中后台项目经验" in query
    assert "Markdown" in query


def test_build_generation_query_with_minimal_fields() -> None:
    query = jd_service.build_generation_query(GenerateJDRequest(title="测试工程师"))

    assert "测试工程师" in query
    assert "- 所属部门：" not in query
    assert "- 技能要求：" not in query


async def test_generate_jd_calls_dify_type1(monkeypatch: pytest.MonkeyPatch) -> None:
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
            type=WorkflowType.JD_GENERATION,
            answer="# 高级前端工程师\n\n## 岗位职责\n负责前端开发",
            conversation_id="conv-1",
            task_id="task-1",
            usage=ChatUsage(total_tokens=42),
        )

    monkeypatch.setattr(dify_service, "chat", fake_chat)
    user_id = uuid4()

    result = await jd_service.generate_jd(make_generate_payload(), user_id=user_id)

    assert result.content.startswith("# 高级前端工程师")
    assert result.conversation_id == "conv-1"
    assert result.task_id == "task-1"
    assert result.workflow_type == "jd_generation"
    assert result.usage is not None and result.usage.total_tokens == 42

    request = captured["request"]
    assert request.type == WorkflowType.JD_GENERATION
    assert "高级前端工程师" in request.query
    assert request.inputs == {}
    assert captured["user_id"] == user_id


async def test_generate_jd_rejects_empty_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_chat(
        request: Any,
        *,
        user_id: UUID | str,
        client: httpx.AsyncClient | None = None,
    ) -> ChatResponse:
        return ChatResponse(type=WorkflowType.JD_GENERATION, answer="   ")

    monkeypatch.setattr(dify_service, "chat", fake_chat)

    with pytest.raises(DifyInvalidResponseError):
        await jd_service.generate_jd(make_generate_payload(), user_id=uuid4())


# ---------------------------------------------------------------------------
# 落库辅助
# ---------------------------------------------------------------------------
async def test_create_jd_sets_created_by() -> None:
    db = FakeWriteSession()
    user_id = uuid4()

    record = await jd_service.create_jd(
        db,  # type: ignore[arg-type]
        JobDescriptionCreate(
            title="前端工程师",
            content="# 岗位职责\n负责前端开发",
            status=JDStatus.GENERATED,
        ),
        user_id=user_id,
    )

    assert db.added is record
    assert record.created_by == user_id
    assert db.commit_count == 1
    assert db.refresh_count == 1


async def test_update_jd_applies_explicit_fields() -> None:
    record = make_jd_record()
    db = FakeWriteSession(record)
    user_id = uuid4()

    updated = await jd_service.update_jd(
        db,  # type: ignore[arg-type]
        record.id,
        JobDescriptionUpdate(title="资深前端工程师", skills=["Vue 3"], status=JDStatus.PUBLISHED),
        user_id=user_id,
    )

    assert updated.title == "资深前端工程师"
    assert updated.skills == ["Vue 3"]
    assert updated.status == JDStatus.PUBLISHED
    assert updated.updated_by == user_id
    assert db.commit_count == 1


async def test_update_jd_rejects_null_content() -> None:
    record = make_jd_record()
    db = FakeWriteSession(record)

    with pytest.raises(WorkflowValidationError):
        await jd_service.update_jd(
            db,  # type: ignore[arg-type]
            record.id,
            JobDescriptionUpdate(content=None),
            user_id=uuid4(),
        )


def test_to_list_item_builds_preview() -> None:
    record = make_jd_record(content="第一行\n\n第二行 " + "内容" * 200)

    item = jd_service.to_list_item(record)

    assert item.id == record.id
    assert item.title == record.title
    assert item.status == JDStatus.GENERATED
    assert "第一行 第二行" in item.content_preview
    assert item.content_preview.endswith("…")
    assert len(item.content_preview) <= 141


def test_strip_markdown_removes_common_syntax() -> None:
    content = "# 岗位职责\n\n- **负责**前端 `Vue` 开发\n\n1. 第一项"

    assert jd_service.strip_markdown(content) == "岗位职责 \u2022 负责前端 Vue 开发 第一项"


def test_to_list_item_removes_leading_title() -> None:
    record = make_jd_record(content="# 高级前端工程师\n\n岗位职责：负责前端开发")

    item = jd_service.to_list_item(record)

    assert item.content_preview.startswith("岗位职责")


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


async def test_stream_generate_jd_emits_delta_and_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_events(
        request: Any,
        *,
        user_id: UUID | str,
        client: httpx.AsyncClient | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        yield {
            "event": "workflow_started",
            "conversation_id": "conv-1",
            "task_id": "task-1",
        }
        yield {"event": "message", "answer": "# 高级前端"}
        yield {"event": "message", "answer": "工程师"}
        yield {
            "event": "message_end",
            "metadata": {"usage": {"total_tokens": 12}},
        }
        yield {
            "event": "workflow_finished",
            "data": {"outputs": {"answer": "# 高级前端工程师"}},
        }

    monkeypatch.setattr(dify_service, "iter_stream_events", fake_events)
    client = httpx.AsyncClient()
    try:
        chunks = [
            chunk
            async for chunk in jd_service.stream_generate_jd(
                make_generate_payload(),
                user_id="u-1",
                client=client,
            )
        ]
    finally:
        await client.aclose()

    frames = _parse_sse_frames(chunks)
    assert [event for event, _ in frames] == ["start", "delta", "delta", "done"]
    assert "".join(data["content"] for event, data in frames if event == "delta") == (
        "# 高级前端工程师"
    )

    done = frames[-1][1]
    assert done["content"] == "# 高级前端工程师"
    assert done["conversation_id"] == "conv-1"
    assert done["task_id"] == "task-1"
    assert done["usage"]["total_tokens"] == 12
    assert done["workflow_type"] == "jd_generation"


async def test_stream_generate_jd_handles_dify_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        chunks = [
            chunk
            async for chunk in jd_service.stream_generate_jd(
                make_generate_payload(),
                user_id="u-1",
                client=client,
            )
        ]
    finally:
        await client.aclose()

    frames = _parse_sse_frames(chunks)
    assert frames[-1][0] == "error"
    assert frames[-1][1]["code"] == "DIFY_INVALID_PARAM"
    assert frames[-1][1]["status"] == 400


async def test_stream_generate_jd_rejects_empty_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        chunks = [
            chunk
            async for chunk in jd_service.stream_generate_jd(
                make_generate_payload(),
                user_id="u-1",
                client=client,
            )
        ]
    finally:
        await client.aclose()

    frames = _parse_sse_frames(chunks)
    assert frames[-1][0] == "error"
    assert frames[-1][1]["code"] == "DIFY_INVALID_RESPONSE"
