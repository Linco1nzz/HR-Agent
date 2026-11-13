"""文档服务测试：处理成功时经 PGVector 写入分块向量，向量化不可用时落库为 failed。"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.core.exceptions import EmbeddingNotConfiguredError
from app.db.models import Document
from app.services import document_service, vector_store_service

_TEXT = ("员工手册第一章：年假制度。\n\n" * 20).encode()


class FakeSession:
    """只实现文档处理链路用到的 AsyncSession 子集。"""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement: Any) -> None:  # noqa: ARG002 - 不解析语句
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, record: Any) -> None:  # noqa: ARG002
        return None

    async def rollback(self) -> None:
        self.rollbacks += 1


def make_document(**overrides: Any) -> Document:
    data: dict[str, Any] = {
        "id": uuid4(),
        "filename": "handbook.txt",
        "original_filename": "员工手册.txt",
        "file_path": "/tmp/handbook.txt",
        "file_size": len(_TEXT),
        "file_hash": "a" * 64,
        "mime_type": "text/plain",
        "processing_status": "uploaded",
        "chunk_count": 0,
        "user_id": uuid4(),
        "is_active": True,
    }
    data.update(overrides)
    return Document(**data)


async def test_process_document_stores_chunks_via_pgvector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_read(_path: str) -> bytes:
        return _TEXT

    captured: dict[str, Any] = {}

    async def fake_add(**kwargs: Any) -> int:
        captured.update(kwargs)
        return len(kwargs["chunks"])

    async def fake_delete(_document_id: Any) -> int:
        return 0

    monkeypatch.setattr(document_service, "_read_file", fake_read)
    monkeypatch.setattr(vector_store_service, "add_document_chunks", fake_add)
    monkeypatch.setattr(vector_store_service, "delete_document_chunks", fake_delete)

    db = FakeSession()
    document = make_document()

    result = await document_service.process_document(db, document)  # type: ignore[arg-type]

    assert result.processing_status == "processed"
    assert result.chunk_count >= 1
    assert result.chunk_count == len(captured["chunks"])
    assert captured["document_id"] == document.id
    assert captured["user_id"] == document.user_id
    assert result.extracted_content is not None and "年假制度" in result.extracted_content
    assert result.processed_at is not None
    assert result.processing_error is None
    assert result.meta_data is not None and result.meta_data["embedding_model"]


async def test_process_document_marks_failed_when_embedding_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_read(_path: str) -> bytes:
        return _TEXT

    async def fake_add(**kwargs: Any) -> int:  # noqa: ARG002
        raise EmbeddingNotConfiguredError()

    async def fake_delete(_document_id: Any) -> int:
        return 0

    monkeypatch.setattr(document_service, "_read_file", fake_read)
    monkeypatch.setattr(vector_store_service, "add_document_chunks", fake_add)
    monkeypatch.setattr(vector_store_service, "delete_document_chunks", fake_delete)

    db = FakeSession()
    document = make_document()

    result = await document_service.process_document(db, document)  # type: ignore[arg-type]

    assert result.processing_status == "failed"
    assert result.chunk_count == 0
    assert "Embedding" in (result.processing_error or "")
    assert db.rollbacks == 1
