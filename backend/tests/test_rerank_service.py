"""Rerank 服务单元测试：成功映射、截断与失败回退（mock httpx，不依赖外部服务）。"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.config import settings
from app.services import rerank_service
from app.services.kb_retrieval_service import RetrievedChunk


def make_chunk(chunk_id: str, rrf_score: float, content: str = "内容") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=chunk_id.split(":")[0],
        document_name="员工手册.txt",
        knowledge_base_id="kb-1",
        chunk_index=0,
        content=content,
        rrf_score=rrf_score,
    )


class FakeResponse:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return self._data


def install_fake_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    results: list[dict[str, Any]] | None = None,
    error: Exception | None = None,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    class FakeAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured["client_kwargs"] = kwargs

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, *exc: Any) -> bool:
            return False

        async def post(
            self,
            url: str,
            json: dict[str, Any] | None = None,
            headers: dict[str, str] | None = None,
        ) -> FakeResponse:
            captured.update({"url": url, "payload": json, "headers": headers})
            if error is not None:
                raise error
            return FakeResponse({"output": {"results": results or []}})

    monkeypatch.setattr(rerank_service.httpx, "AsyncClient", FakeAsyncClient)
    return captured


@pytest.fixture(autouse=True)
def configured_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "dashscope_api_key", "test-key")


async def test_rerank_empty_candidates() -> None:
    assert await rerank_service.rerank("问题", []) == []


async def test_rerank_maps_indexes_and_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    candidates = [make_chunk("a:0", 0.03), make_chunk("b:0", 0.02), make_chunk("c:0", 0.01)]
    captured = install_fake_client(
        monkeypatch,
        results=[
            {"index": 2, "relevance_score": 0.91},
            {"index": 0, "relevance_score": 0.55},
        ],
    )

    ranked = await rerank_service.rerank("年假有几天", candidates)

    assert [(chunk.chunk_id, score) for chunk, score in ranked] == [("c:0", 0.91), ("a:0", 0.55)]
    assert captured["url"] == settings.rerank_base_url
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    payload = captured["payload"]
    assert payload["model"] == settings.rerank_model
    assert payload["input"]["query"] == "年假有几天"
    assert payload["input"]["documents"] == [chunk.content for chunk in candidates]
    assert payload["parameters"] == {
        "top_n": min(settings.qa_top_k, len(candidates)),
        "return_documents": False,
    }


async def test_rerank_truncates_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rerank_max_doc_chars", 10)
    candidates = [make_chunk("a:0", 0.03, content="超" * 50)]
    captured = install_fake_client(monkeypatch, results=[{"index": 0, "relevance_score": 0.9}])

    await rerank_service.rerank("问题", candidates)

    assert captured["payload"]["input"]["documents"] == ["超" * 10]


async def test_rerank_ignores_invalid_indexes(monkeypatch: pytest.MonkeyPatch) -> None:
    candidates = [make_chunk("a:0", 0.03)]
    install_fake_client(
        monkeypatch,
        results=[{"index": 9, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.4}],
    )

    ranked = await rerank_service.rerank("问题", candidates)

    assert [(chunk.chunk_id, score) for chunk, score in ranked] == [("a:0", 0.4)]


async def test_rerank_without_key_falls_back_to_rrf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "dashscope_api_key", None)
    monkeypatch.setattr(settings, "qa_top_k", 2)
    candidates = [make_chunk("a:0", 0.01), make_chunk("b:0", 0.03), make_chunk("c:0", 0.02)]

    ranked = await rerank_service.rerank("问题", candidates)

    assert [(chunk.chunk_id, score) for chunk, score in ranked] == [("b:0", 0.03), ("c:0", 0.02)]


async def test_rerank_request_failure_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "qa_top_k", 2)
    candidates = [make_chunk("a:0", 0.01), make_chunk("b:0", 0.03), make_chunk("c:0", 0.02)]
    install_fake_client(monkeypatch, error=httpx.ConnectTimeout("超时"))

    ranked = await rerank_service.rerank("问题", candidates)

    assert [chunk.chunk_id for chunk, _ in ranked] == ["b:0", "c:0"]
    assert all(score == chunk.rrf_score for chunk, score in ranked)


async def test_rerank_empty_results_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    candidates = [make_chunk("a:0", 0.03)]
    install_fake_client(monkeypatch, results=[])

    ranked = await rerank_service.rerank("问题", candidates)

    assert [(chunk.chunk_id, score) for chunk, score in ranked] == [("a:0", 0.03)]
