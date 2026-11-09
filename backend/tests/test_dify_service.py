"""Dify Chatflow 服务层单元测试（使用 httpx.MockTransport，不依赖真实 Dify）。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import uuid4

import httpx
import pytest

from app.core.config import settings
from app.core.exceptions import (
    DifyInvalidParamError,
    DifyInvalidResponseError,
    DifyNotConfiguredError,
    DifyUnauthorizedError,
    DifyUnavailableError,
    WorkflowValidationError,
)
from app.schemas.ai import ChatRequest, WorkflowType
from app.services import dify_service

Handler = Callable[[httpx.Request], httpx.Response]


def make_payload(**overrides: Any) -> ChatRequest:
    data: dict[str, Any] = {
        "type": WorkflowType.JD_GENERATION,
        "query": "招聘一名前端工程师",
    }
    data.update(overrides)
    return ChatRequest(**data)


def make_client(handler: Handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def parse_sse_error(body: bytes) -> dict[str, Any]:
    text = body.decode()
    assert text.startswith("data: ")
    return json.loads(text.removeprefix("data: ").strip())


# ---------------------------------------------------------------------------
# 类型与入参校验
# ---------------------------------------------------------------------------
def test_workflow_type_specs_cover_all_types() -> None:
    assert set(dify_service.WORKFLOW_TYPE_SPECS) == set(WorkflowType)
    assert [int(item.type) for item in dify_service.list_workflow_types()] == [1, 2, 3, 4, 5, 6]


def test_list_workflow_types_contains_contract() -> None:
    items = {int(item.type): item for item in dify_service.list_workflow_types()}

    assert items[1].key == "jd_generation"
    assert items[1].query_required is True
    assert items[3].required_inputs == ["jianli"]
    assert items[4].query_required is False
    assert set(items[4].required_inputs) == {"jd", "jianli"}
    assert items[5].required_inputs == ["fileContent"]


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        (make_payload(query="   "), "query"),
        (make_payload(type=WorkflowType.RESUME_EVALUATION, query="评价标准"), "jianli"),
        (
            make_payload(
                type=WorkflowType.INTERVIEW_PLAN,
                query="",
                inputs={"jd": "JD", "jianli": "  "},
            ),
            "jianli",
        ),
        (
            make_payload(
                type=WorkflowType.EXAM_GENERATION,
                query="10 道单选题",
                inputs={},
            ),
            "fileContent",
        ),
        (make_payload(type=WorkflowType.EXAM_GRADING, query=""), "query"),
    ],
    ids=["type1-query", "type3-jianli", "type4-jianli", "type5-fileContent", "type6-query"],
)
def test_validate_chat_request_rejects_missing_input(payload: ChatRequest, field: str) -> None:
    with pytest.raises(WorkflowValidationError) as exc_info:
        dify_service.validate_chat_request(payload)

    assert field in str(exc_info.value.details)


def test_validate_type4_allows_empty_query() -> None:
    dify_service.validate_chat_request(
        make_payload(
            type=WorkflowType.INTERVIEW_PLAN,
            query="",
            inputs={"jd": "岗位职责", "jianli": "候选人简历"},
        )
    )


def test_validate_rejects_oversized_input() -> None:
    payload = make_payload(inputs={"jd": "x" * 48_001})

    with pytest.raises(WorkflowValidationError) as exc_info:
        dify_service.validate_chat_request(payload)

    assert exc_info.value.details is not None
    assert exc_info.value.details["field"] == "inputs.jd"


def test_build_chat_payload_uses_default_query_for_type4() -> None:
    payload = make_payload(
        type=WorkflowType.INTERVIEW_PLAN,
        query="",
        inputs={"jd": "JD", "jianli": "简历"},
    )

    body = dify_service.build_chat_payload(payload, user_id="u-1", response_mode="blocking")

    assert body["query"] == "请根据 JD 和简历生成面试方案与面试题"


def test_build_chat_payload_merges_type_and_drops_none() -> None:
    payload = make_payload(
        inputs={"type": 6, "jd": "JD", "jianli": None},
        conversation_id="conv-1",
        auto_generate_name=False,
    )

    body = dify_service.build_chat_payload(payload, user_id="user-1", response_mode="blocking")

    assert body["query"] == payload.query
    assert body["inputs"] == {"type": 1, "jd": "JD"}
    assert body["user"] == "user-1"
    assert body["response_mode"] == "blocking"
    assert body["conversation_id"] == "conv-1"
    assert body["auto_generate_name"] is False
    assert "files" not in body


# ---------------------------------------------------------------------------
# 阻塞调用
# ---------------------------------------------------------------------------
async def test_chat_blocking_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "dify_base_url", "http://dify.test/v1")
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "event": "message",
                "task_id": "task-1",
                "message_id": "msg-1",
                "conversation_id": "conv-1",
                "mode": "advanced-chat",
                "answer": "这是一份 JD",
                "created_at": 1_700_000_000,
                "metadata": {
                    "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                    "retriever_resources": [{"dataset_name": "hr"}],
                },
            },
        )

    async with make_client(handler) as client:
        result = await dify_service.chat(make_payload(), user_id=uuid4(), client=client)

    assert result.answer == "这是一份 JD"
    assert result.conversation_id == "conv-1"
    assert result.type == WorkflowType.JD_GENERATION
    assert result.usage is not None and result.usage.total_tokens == 30
    assert result.retriever_resources == [{"dataset_name": "hr"}]

    request = captured[0]
    assert str(request.url) == "http://dify.test/v1/chat-messages"
    assert request.headers["Accept"] == "application/json"
    sent = json.loads(request.content)
    assert sent["response_mode"] == "blocking"
    assert sent["inputs"]["type"] == 1


async def test_chat_maps_400_to_invalid_param() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"code": "invalid_param", "message": "inputs.type is required"},
        )

    async with make_client(handler) as client:
        with pytest.raises(DifyInvalidParamError) as exc_info:
            await dify_service.chat(make_payload(), user_id=uuid4(), client=client)

    assert exc_info.value.status_code == 422
    assert exc_info.value.details is not None
    assert exc_info.value.details["dify_code"] == "invalid_param"


async def test_chat_maps_401_to_unauthorized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"code": "unauthorized", "message": "bad key"})

    async with make_client(handler) as client:
        with pytest.raises(DifyUnauthorizedError):
            await dify_service.chat(make_payload(), user_id=uuid4(), client=client)


async def test_chat_maps_500_to_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"code": "internal_error", "message": "boom"})

    async with make_client(handler) as client:
        with pytest.raises(DifyUnavailableError):
            await dify_service.chat(make_payload(), user_id=uuid4(), client=client)


async def test_chat_maps_timeout_to_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    async with make_client(handler) as client:
        with pytest.raises(DifyUnavailableError):
            await dify_service.chat(make_payload(), user_id=uuid4(), client=client)


async def test_chat_rejects_invalid_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    async with make_client(handler) as client:
        with pytest.raises(DifyInvalidResponseError):
            await dify_service.chat(make_payload(), user_id=uuid4(), client=client)


async def test_chat_rejects_missing_answer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"event": "message", "conversation_id": "c"})

    async with make_client(handler) as client:
        with pytest.raises(DifyInvalidResponseError):
            await dify_service.chat(make_payload(), user_id=uuid4(), client=client)


# ---------------------------------------------------------------------------
# 流式调用
# ---------------------------------------------------------------------------
async def test_stream_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "dify_base_url", "http://dify.test/v1")
    captured: list[httpx.Request] = []
    payload = b'data: {"event":"message","answer":"hi"}\n\n'

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=payload,
        )

    async with make_client(handler) as client:
        stream = dify_service.stream_chat(make_payload(), user_id="u-1", client=client)
        chunks: list[bytes] = [chunk async for chunk in stream]

    assert b"".join(chunks) == payload
    sent = json.loads(captured[0].content)
    assert sent["response_mode"] == "streaming"
    assert captured[0].headers["Accept"] == "text/event-stream"


async def test_stream_upstream_error_becomes_sse_event() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"code": "internal_error", "message": "boom"})

    async with make_client(handler) as client:
        stream = dify_service.stream_chat(make_payload(), user_id="u-1", client=client)
        chunks: list[bytes] = [chunk async for chunk in stream]

    event = parse_sse_error(b"".join(chunks))
    assert event["event"] == "error"
    assert event["code"] == "DIFY_UNAVAILABLE"
    assert event["status"] == 503


async def test_iter_stream_events_parses_split_frames() -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield b"event: ping\n\n"
        yield b'data: {"event":"message","answer":"\xe4\xbd\xa0"}\n\n'
        yield b'data: {"event":"mess'
        yield b'age_end"}\n\n'

    events = [event async for event in dify_service._iter_sse_json(chunks())]

    assert [event["event"] for event in events] == ["message", "message_end"]
    assert events[0]["answer"] == "你"


async def test_iter_stream_events_handles_crlf_and_ignores_non_json() -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield b'data: {"event":"message","answer":"hi"}\r\n\r\n'
        yield b": keep-alive\n\n"
        yield b"data: not-json\n\n"

    events = [event async for event in dify_service._iter_sse_json(chunks())]

    assert events == [{"event": "message", "answer": "hi"}]


async def test_stream_connection_error_becomes_sse_event() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async with make_client(handler) as client:
        stream = dify_service.stream_chat(make_payload(), user_id="u-1", client=client)
        chunks: list[bytes] = [chunk async for chunk in stream]

    event = parse_sse_error(b"".join(chunks))
    assert event["event"] == "error"
    assert event["code"] == "DIFY_UNAVAILABLE"


# ---------------------------------------------------------------------------
# 参数与客户端
# ---------------------------------------------------------------------------
async def test_get_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "dify_base_url", "http://dify.test/v1")

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://dify.test/v1/parameters"
        return httpx.Response(
            200,
            json={
                "opening_statement": "你好",
                "suggested_questions": ["生成 JD"],
                "user_input_form": [{"number": {"variable": "type"}}],
            },
        )

    async with make_client(handler) as client:
        data = await dify_service.get_parameters(client=client)

    assert data["opening_statement"] == "你好"
    assert data["suggested_questions"] == ["生成 JD"]


async def test_get_client_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "dify_api_key", None)
    monkeypatch.setattr(dify_service, "_client", None)

    with pytest.raises(DifyNotConfiguredError):
        dify_service.get_client()


async def test_get_client_sets_bearer_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "dify_api_key", "app-test")
    monkeypatch.setattr(settings, "dify_base_url", "http://dify.test/v1")
    monkeypatch.setattr(dify_service, "_client", None)

    client = dify_service.get_client()
    try:
        assert client.headers["Authorization"] == "Bearer app-test"
    finally:
        await dify_service.close_client()
