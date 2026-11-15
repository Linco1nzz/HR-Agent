"""混合检索单元测试：RRF 融合、相似度过滤与降级路径（不依赖数据库）。"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from langchain_core.documents import Document as LCDocument

from app.core.config import settings
from app.services import embedding_service, kb_retrieval_service, vector_store_service
from app.services.kb_retrieval_service import RetrievedChunk


def make_chunk(chunk_id: str, **overrides: Any) -> RetrievedChunk:
    data: dict[str, Any] = {
        "chunk_id": chunk_id,
        "document_id": chunk_id.split(":")[0],
        "document_name": "员工手册.txt",
        "knowledge_base_id": "kb-1",
        "chunk_index": int(chunk_id.split(":")[-1]),
        "content": f"内容 {chunk_id}",
    }
    data.update(overrides)
    return RetrievedChunk(**data)


# ---------------------------------------------------------------------------
# RRF 融合
# ---------------------------------------------------------------------------
def test_merge_rrf_dedupes_and_ranks() -> None:
    vector = [make_chunk("a:0", vector_score=0.9), make_chunk("b:0", vector_score=0.8)]
    keyword = [make_chunk("b:0", keyword_score=2), make_chunk("c:0", keyword_score=1)]

    merged = kb_retrieval_service.merge_rrf(vector, keyword)

    assert [chunk.chunk_id for chunk in merged] == ["b:0", "a:0", "c:0"]
    top = merged[0]
    # b 在向量路排第 2、关键词路排第 1：1/62 + 1/61
    assert top.rrf_score == pytest.approx(1 / 62 + 1 / 61)
    assert top.vector_score == 0.8
    assert top.keyword_score == 2
    assert merged[1].rrf_score == pytest.approx(1 / 61)
    assert merged[2].rrf_score == pytest.approx(1 / 62)


def test_merge_rrf_does_not_mutate_inputs() -> None:
    vector = [make_chunk("a:0", vector_score=0.9)]

    kb_retrieval_service.merge_rrf(vector, [])

    assert vector[0].rrf_score == 0.0


def test_merge_rrf_respects_limit() -> None:
    vector = [make_chunk(f"a:{index}") for index in range(10)]

    merged = kb_retrieval_service.merge_rrf(vector, [], limit=3)

    assert len(merged) == 3


def test_merge_rrf_empty_inputs() -> None:
    assert kb_retrieval_service.merge_rrf([], []) == []


# ---------------------------------------------------------------------------
# retrieve 编排
# ---------------------------------------------------------------------------
async def test_retrieve_without_kb_returns_empty() -> None:
    assert await kb_retrieval_service.retrieve("问题", ["关键词"], []) == []


async def test_retrieve_merges_both_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    kb_id = uuid4()
    captured: dict[str, Any] = {}

    async def fake_vector(query: str, kb_ids: list[str]) -> list[RetrievedChunk]:
        captured["vector"] = (query, kb_ids)
        return [make_chunk("a:0", vector_score=0.9)]

    async def fake_keyword(keywords: list[str], kb_ids: list[str]) -> list[RetrievedChunk]:
        captured["keyword"] = (keywords, kb_ids)
        return [make_chunk("a:0", keyword_score=1)]

    monkeypatch.setattr(kb_retrieval_service, "_vector_recall", fake_vector)
    monkeypatch.setattr(kb_retrieval_service, "_keyword_recall", fake_keyword)

    merged = await kb_retrieval_service.retrieve("改写后的问题", ["年假"], [kb_id])

    assert captured["vector"] == ("改写后的问题", [str(kb_id)])
    assert captured["keyword"] == (["年假"], [str(kb_id)])
    assert len(merged) == 1
    assert merged[0].rrf_score == pytest.approx(2 / 61)


# ---------------------------------------------------------------------------
# 向量路
# ---------------------------------------------------------------------------
class FakeStore:
    def __init__(self, results: list[tuple[LCDocument, float]]) -> None:
        self.results = results
        self.captured: dict[str, Any] = {}

    async def asimilarity_search_with_score(
        self, query: str, k: int = 4, filter: dict | None = None
    ) -> list[tuple[LCDocument, float]]:
        self.captured = {"query": query, "k": k, "filter": filter}
        return self.results


def make_lc_doc(chunk_id: str) -> LCDocument:
    document_id, chunk_index = chunk_id.split(":")
    return LCDocument(
        id=chunk_id,
        page_content="带薪年假规定",
        metadata={
            "document_id": document_id,
            "knowledge_base_id": "kb-1",
            "original_filename": "员工手册.txt",
            "chunk_index": int(chunk_index),
        },
    )


async def test_vector_recall_filters_low_similarity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedding_service, "is_configured", lambda: True)
    store = FakeStore(
        [
            (make_lc_doc("d:0"), 0.2),  # similarity 0.8，保留
            (make_lc_doc("d:1"), 0.9),  # similarity 0.1，低于 0.30 丢弃
        ]
    )
    monkeypatch.setattr(vector_store_service, "get_store", lambda: store)

    chunks = await kb_retrieval_service._vector_recall("年假", ["kb-1"])

    assert store.captured["filter"] == {"knowledge_base_id": {"$in": ["kb-1"]}}
    assert store.captured["k"] == settings.qa_recall_k
    assert len(chunks) == 1
    assert chunks[0].chunk_id == "d:0"
    assert chunks[0].vector_score == pytest.approx(0.8)
    assert chunks[0].document_name == "员工手册.txt"


async def test_vector_recall_without_embedding_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedding_service, "is_configured", lambda: False)

    assert await kb_retrieval_service._vector_recall("年假", ["kb-1"]) == []


async def test_vector_recall_failure_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedding_service, "is_configured", lambda: True)

    class BrokenStore:
        async def asimilarity_search_with_score(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("embedding 服务不可用")

    monkeypatch.setattr(vector_store_service, "get_store", lambda: BrokenStore())

    assert await kb_retrieval_service._vector_recall("年假", ["kb-1"]) == []


async def test_keyword_recall_without_keywords_returns_empty() -> None:
    assert await kb_retrieval_service._keyword_recall([], ["kb-1"]) == []
    assert await kb_retrieval_service._keyword_recall(["  "], ["kb-1"]) == []
