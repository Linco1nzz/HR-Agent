"""文档切块服务测试：LLM 分割点解析、语义分割与长度约束。"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.core.exceptions import DocumentProcessingError
from app.services import document_chunking_service as chunking

_PARA = "这是一段用于测试切块的中文内容，包含标点符号。" * 12


def test_parse_split_points_from_code_fence() -> None:
    points = chunking._parse_split_points('```json\n{"split_points": [3, 5, 3]}\n```')

    assert points == [3, 5]


def test_parse_split_points_accepts_aliases_and_dicts() -> None:
    assert chunking._parse_split_points('{"points": [{"index": 2}]}') == [2]
    assert chunking._parse_split_points('{"分割点": [4]}') == [4]
    assert chunking._parse_split_points("[2, 6]") == [2, 6]


def test_parse_split_points_ignores_invalid_values() -> None:
    assert chunking._parse_split_points("没有任何 JSON") == []
    assert chunking._parse_split_points('{"split_points": [1, "x", null]}') == []


def test_offsets_from_points_skips_invalid_positions() -> None:
    text = "a" * 10 + "b" * 10 + "c" * 10
    paragraphs = [
        chunking._Paragraph("a" * 10, 0),
        chunking._Paragraph("b" * 10, 10),
        chunking._Paragraph("c" * 10, 20),
    ]

    offsets = chunking._offsets_from_points(text, paragraphs, [1, 2, 99])

    assert offsets == [10]


def test_slice_by_offsets_keeps_full_text() -> None:
    text = "aaaa\nbbbb\ncccc"

    segments = chunking._slice_by_offsets(text, [5, 10])

    assert segments == ["aaaa\n", "bbbb\n", "cccc"]
    assert "".join(segments) == text


async def test_ask_for_split_points_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "deepseek_api_key", None)

    assert await chunking._ask_for_split_points("prompt") == []


async def test_ask_for_split_points_falls_back_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")

    def boom() -> None:
        raise RuntimeError("LLM 不可用")

    monkeypatch.setattr(chunking, "_build_chat_model", boom)

    assert await chunking._ask_for_split_points("prompt") == []


async def test_split_into_chunks_uses_llm_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "knowledge_base_chunk_size", 300)
    monkeypatch.setattr(settings, "knowledge_base_chunk_overlap", 30)
    monkeypatch.setattr(settings, "knowledge_base_min_chunk_chars", 10)

    async def fake_points(_prompt: str) -> list[int]:
        return [3]

    monkeypatch.setattr(chunking, "_ask_for_split_points", fake_points)

    text = f"第一段{_PARA * 2}\n\n第二段{_PARA * 2}\n\n第三段{_PARA * 2}"
    chunks = await chunking.split_into_chunks(text)

    assert chunks[0].startswith("第一段")
    assert any(chunk.startswith("第三段") for chunk in chunks)
    assert all(len(chunk) <= 330 for chunk in chunks)


async def test_split_into_chunks_truncates_to_max_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "knowledge_base_chunk_size", 100)
    monkeypatch.setattr(settings, "knowledge_base_chunk_overlap", 0)
    monkeypatch.setattr(settings, "knowledge_base_min_chunk_chars", 2)
    monkeypatch.setattr(settings, "knowledge_base_max_chunks", 2)

    chunks = await chunking.split_into_chunks(_PARA)

    assert len(chunks) == 2


async def test_split_into_chunks_rejects_empty_text() -> None:
    with pytest.raises(DocumentProcessingError):
        await chunking.split_into_chunks("   \n\n  ")


def test_merge_short_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "knowledge_base_chunk_size", 100)
    monkeypatch.setattr(settings, "knowledge_base_chunk_overlap", 0)
    monkeypatch.setattr(settings, "knowledge_base_min_chunk_chars", 20)

    merged = chunking._merge_short_chunks(["a" * 90, "bbb"])

    assert merged == ["a" * 90 + "\nbbb"]


def test_merge_short_tail_when_within_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "knowledge_base_chunk_size", 100)
    monkeypatch.setattr(settings, "knowledge_base_chunk_overlap", 10)
    monkeypatch.setattr(settings, "knowledge_base_min_chunk_chars", 20)

    merged = chunking._merge_short_chunks(["a" * 90, "b" * 15])

    assert len(merged) == 1
    assert merged[0].endswith("b" * 15)
