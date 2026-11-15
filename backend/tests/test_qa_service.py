"""问答编排单元测试：路由 / 改写解析与回退、提示词组装、chat 事件流（mock LLM）。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage

from app.core.config import settings
from app.db.models import User
from app.services import kb_retrieval_service, qa_service, rerank_service
from app.services.kb_retrieval_service import RetrievedChunk
from tests.fakes import make_user


class FakeChatModel:
    def __init__(self, content: str | None = None, error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.prompts: list[Any] = []

    async def ainvoke(self, messages: Any) -> AIMessage:
        self.prompts.append(messages)
        if self.error is not None:
            raise self.error
        return AIMessage(content=self.content or "")


@pytest.fixture(autouse=True)
def configured_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")


def install_model(monkeypatch: pytest.MonkeyPatch, model: FakeChatModel) -> FakeChatModel:
    monkeypatch.setattr(qa_service, "_build_chat_model", lambda: model)
    return model


KB_BRIEFS = [qa_service.KbBrief(name="员工手册", description="公司制度与假期规定")]


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
async def test_route_question_parses_strict_json(monkeypatch: pytest.MonkeyPatch) -> None:
    install_model(monkeypatch, FakeChatModel(content='{"use_kb": true, "reason": "涉及员工手册"}'))

    decision = await qa_service.route_question("年假有几天", KB_BRIEFS, [])

    assert decision == {"use_kb": True, "reason": "涉及员工手册"}


async def test_route_question_parses_fenced_json(monkeypatch: pytest.MonkeyPatch) -> None:
    install_model(
        monkeypatch,
        FakeChatModel(content='```json\n{"use_kb": false, "reason": "闲聊",}\n```'),
    )

    decision = await qa_service.route_question("你好", KB_BRIEFS, [])

    assert decision["use_kb"] is False
    assert decision["reason"] == "闲聊"


async def test_route_question_string_boolean(monkeypatch: pytest.MonkeyPatch) -> None:
    install_model(monkeypatch, FakeChatModel(content='{"use_kb": "false", "reason": "常识"}'))

    decision = await qa_service.route_question("1+1等于几", KB_BRIEFS, [])

    assert decision["use_kb"] is False


async def test_route_question_garbage_falls_back_to_kb(monkeypatch: pytest.MonkeyPatch) -> None:
    install_model(monkeypatch, FakeChatModel(content="抱歉我无法回答"))

    decision = await qa_service.route_question("年假有几天", KB_BRIEFS, [])

    assert decision["use_kb"] is True


async def test_route_question_garbage_without_kb_falls_back_direct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_model(monkeypatch, FakeChatModel(content="不是 JSON"))

    decision = await qa_service.route_question("你好", [], [])

    assert decision["use_kb"] is False


async def test_route_question_llm_failure_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    install_model(monkeypatch, FakeChatModel(error=RuntimeError("LLM 不可用")))

    decision = await qa_service.route_question("年假有几天", KB_BRIEFS, [])

    assert decision["use_kb"] is True


async def test_route_question_without_key_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "deepseek_api_key", None)

    assert (await qa_service.route_question("年假", KB_BRIEFS, []))["use_kb"] is True
    assert (await qa_service.route_question("你好", [], []))["use_kb"] is False


# ---------------------------------------------------------------------------
# 查询改写
# ---------------------------------------------------------------------------
async def test_enhance_query_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    install_model(
        monkeypatch,
        FakeChatModel(
            content=(
                '{"rewritten_query": "员工手册中年假天数规定", '
                '"keywords": ["年假", "带薪年假", "假期", "年假", "  "]}'
            )
        ),
    )

    enhanced = await qa_service.enhance_query("那它有多少天", [("user", "年假是什么")])

    assert enhanced["rewritten_query"] == "员工手册中年假天数规定"
    assert enhanced["keywords"] == ["年假", "带薪年假", "假期"]


async def test_enhance_query_garbage_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    install_model(monkeypatch, FakeChatModel(content="无法改写"))

    enhanced = await qa_service.enhance_query("年假有几天", [])

    assert enhanced == {"rewritten_query": "年假有几天", "keywords": []}


async def test_enhance_query_failure_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    install_model(monkeypatch, FakeChatModel(error=RuntimeError("超时")))

    enhanced = await qa_service.enhance_query("年假有几天", [])

    assert enhanced == {"rewritten_query": "年假有几天", "keywords": []}


async def test_enhance_query_without_key_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "deepseek_api_key", None)

    enhanced = await qa_service.enhance_query("年假有几天", [])

    assert enhanced == {"rewritten_query": "年假有几天", "keywords": []}


# ---------------------------------------------------------------------------
# 回答提示词
# ---------------------------------------------------------------------------
def test_build_answer_messages_kb_with_sources() -> None:
    sources = [{"document_name": "员工手册.txt", "content": "年假 5 天", "score": 0.9}]
    history = [("user", "上一问"), ("assistant", "上一答")]

    messages = qa_service.build_answer_messages(
        "年假几天", history=history, sources=sources, route="kb"
    )

    assert isinstance(messages[0], SystemMessage)
    assert "[1] 文档：员工手册.txt" in messages[0].content
    assert "年假 5 天" in messages[0].content
    assert "[n]" in messages[0].content
    assert isinstance(messages[1], HumanMessage)
    assert isinstance(messages[2], AIMessage)
    assert isinstance(messages[-1], HumanMessage)
    assert messages[-1].content == "年假几天"


def test_build_answer_messages_kb_without_sources() -> None:
    messages = qa_service.build_answer_messages("年假几天", history=[], sources=[], route="kb")

    assert "未找到" in messages[0].content


def test_build_answer_messages_direct() -> None:
    messages = qa_service.build_answer_messages("你好", history=[], sources=[], route="direct")

    assert "HR 助手" in messages[0].content
    assert len(messages) == 2


# ---------------------------------------------------------------------------
# chat 事件流（mock 全部外部步骤）
# ---------------------------------------------------------------------------
def make_chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="d:0",
        document_id="d",
        document_name="员工手册.txt",
        knowledge_base_id="kb-1",
        chunk_index=0,
        content="年假 5 天",
        rrf_score=0.03,
    )


def make_context(user: User, *, with_kb: bool = True) -> qa_service._ChatContext:
    return qa_service._ChatContext(
        conversation_id=uuid4(),
        knowledge_base_ids=[uuid4()] if with_kb else [],
        kb_briefs=KB_BRIEFS if with_kb else [],
        history=[],
        last_message_id=None,
    )


def install_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    ctx: qa_service._ChatContext,
    *,
    stream_chunks: list[AIMessageChunk] | None = None,
    stream_error: Exception | None = None,
) -> dict[str, Any]:
    calls: dict[str, Any] = {"persisted": []}

    async def fake_load(conversation_id: UUID, *, user: User) -> qa_service._ChatContext:
        calls["loaded"] = conversation_id
        return ctx

    async def fake_persist_user(
        ctx: qa_service._ChatContext, content: str, *, user_message_id: UUID, user_id: UUID
    ) -> None:
        calls["persisted"].append(("user", content, user_message_id))

    async def fake_persist_assistant(ctx: qa_service._ChatContext, **kwargs: Any) -> None:
        calls["persisted"].append(("assistant", kwargs))

    async def fake_route(question: str, kb_briefs: Any, history: Any) -> dict[str, Any]:
        calls["routed"] = question
        return {"use_kb": True, "reason": "涉及员工手册"}

    async def fake_enhance(question: str, history: Any) -> dict[str, Any]:
        return {"rewritten_query": "员工手册年假规定", "keywords": ["年假"]}

    async def fake_retrieve(
        query: str, keywords: list[str], kb_ids: list[UUID]
    ) -> list[RetrievedChunk]:
        calls["retrieved"] = (query, keywords)
        return [make_chunk()]

    async def fake_rerank(
        query: str, candidates: list[RetrievedChunk]
    ) -> list[tuple[RetrievedChunk, float]]:
        return [(chunk, 0.87) for chunk in candidates]

    async def fake_stream(question: str, **kwargs: Any) -> AsyncIterator[AIMessageChunk]:
        calls["answer_kwargs"] = kwargs
        for chunk in stream_chunks or []:
            yield chunk
        if stream_error is not None:
            raise stream_error

    monkeypatch.setattr(qa_service, "_load_chat_context", fake_load)
    monkeypatch.setattr(qa_service, "_persist_user_message", fake_persist_user)
    monkeypatch.setattr(qa_service, "_persist_assistant_message", fake_persist_assistant)
    monkeypatch.setattr(qa_service, "route_question", fake_route)
    monkeypatch.setattr(qa_service, "enhance_query", fake_enhance)
    monkeypatch.setattr(kb_retrieval_service, "retrieve", fake_retrieve)
    monkeypatch.setattr(rerank_service, "rerank", fake_rerank)
    monkeypatch.setattr(qa_service, "stream_answer", fake_stream)
    return calls


async def collect_events(
    conversation_id: UUID, content: str, user: User
) -> list[tuple[str, dict[str, Any]]]:
    return [event async for event in qa_service.chat(conversation_id, content, user=user)]


async def test_chat_kb_route_event_sequence(monkeypatch: pytest.MonkeyPatch) -> None:
    user = make_user()
    ctx = make_context(user)
    chunks = [
        AIMessageChunk(content="年假"),
        AIMessageChunk(content="有 5 天 [1]"),
        AIMessageChunk(
            content="", usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        ),
    ]
    calls = install_pipeline(monkeypatch, ctx, stream_chunks=chunks)

    events = await collect_events(ctx.conversation_id, "年假有几天", user)

    assert [name for name, _ in events] == ["meta", "sources", "delta", "delta", "done"]
    meta = events[0][1]
    assert meta["route"] == "kb"
    assert meta["rewritten_query"] == "员工手册年假规定"
    assert meta["keywords"] == ["年假"]
    UUID(meta["user_message_id"])
    UUID(meta["assistant_message_id"])
    sources = events[1][1]["sources"]
    assert len(sources) == 1
    assert sources[0]["score"] == 0.87
    assert sources[0]["document_name"] == "员工手册.txt"
    assert "".join(data["content"] for name, data in events if name == "delta") == "年假有 5 天 [1]"
    done = events[-1][1]
    assert done["message_id"] == meta["assistant_message_id"]
    assert done["tokens_used"] == 15
    assert done["model_name"] == settings.deepseek_model
    assert calls["retrieved"] == ("员工手册年假规定", ["年假"])
    # 用户消息与助手消息各落库一次
    assert [entry[0] for entry in calls["persisted"]] == ["user", "assistant"]
    assert calls["persisted"][0][2] == UUID(meta["user_message_id"])
    assistant_kwargs = calls["persisted"][1][1]
    assert assistant_kwargs["content"] == "年假有 5 天 [1]"
    assert assistant_kwargs["context"]["sources"] == sources
    assert assistant_kwargs.get("error") is None
    # 助手消息挂在用户消息之下，且 ID 与 meta 预告一致
    assert assistant_kwargs["user_message_id"] == UUID(meta["user_message_id"])
    assert assistant_kwargs["message_id"] == UUID(meta["assistant_message_id"])


async def test_chat_direct_route_skips_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    user = make_user()
    ctx = make_context(user, with_kb=False)
    calls = install_pipeline(monkeypatch, ctx, stream_chunks=[AIMessageChunk(content="你好！")])

    events = await collect_events(ctx.conversation_id, "你好", user)

    assert [name for name, _ in events] == ["meta", "delta", "done"]
    assert events[0][1]["route"] == "direct"
    assert "routed" not in calls
    assert "retrieved" not in calls
    assert calls["answer_kwargs"]["route"] == "direct"


async def test_chat_stream_error_persists_partial(monkeypatch: pytest.MonkeyPatch) -> None:
    user = make_user()
    ctx = make_context(user)
    calls = install_pipeline(
        monkeypatch,
        ctx,
        stream_chunks=[AIMessageChunk(content="部分回答")],
        stream_error=RuntimeError("连接中断"),
    )

    events = await collect_events(ctx.conversation_id, "年假有几天", user)

    assert [name for name, _ in events] == ["meta", "sources", "delta", "error"]
    assert events[-1][1]["code"] == "QA_STREAM_FAILED"
    assert events[2][1]["content"] == "部分回答"
    # 部分内容仍然落库，且记录错误信息
    assert [entry[0] for entry in calls["persisted"]] == ["user", "assistant"]
    assistant_kwargs = calls["persisted"][1][1]
    assert assistant_kwargs["content"] == "部分回答"
    assert assistant_kwargs["error"] == "连接中断"


async def test_chat_without_key_yields_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "deepseek_api_key", None)
    user = make_user()
    ctx = make_context(user)
    calls = install_pipeline(monkeypatch, ctx)

    events = await collect_events(ctx.conversation_id, "年假有几天", user)

    assert [name for name, _ in events] == ["error"]
    assert events[0][1]["code"] == "QA_NOT_CONFIGURED"
    assert calls["persisted"] == []
