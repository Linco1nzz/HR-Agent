"""知识库向量存储：LangChain PGVector（``langchain_pg_embedding`` 表）。

分块文本与向量统一交给 :class:`langchain_postgres.PGVector` 管理，落在它自建的
``langchain_pg_collection`` / ``langchain_pg_embedding`` 两张表里：

* 所有知识库共用一个 collection（``settings.pgvector_collection_name``），
  每个分块的 ``cmetadata`` 携带 ``document_id`` / ``knowledge_base_id`` /
  ``chunk_index`` 等字段，用于按文档过滤、排序与删除；
* 向量由 :mod:`app.services.embedding_service` 预先算好，再通过
  ``aadd_embeddings`` 写入（按分块 id upsert，重新处理时原地覆盖）；
* 删除知识库不动向量（文档仅解除关联）；删除文档时按 ``document_id`` 清理向量。

这两张表由 PGVector 在首次使用时惰性创建，不属于业务 ORM 元数据，
Alembic 通过 ``include_name`` 将其排除在自动生成之外。
"""

from __future__ import annotations

from functools import lru_cache
from uuid import UUID

from langchain_core.embeddings import Embeddings
from langchain_postgres import PGVector
from sqlalchemy import Integer, cast, delete, select

from app.core.config import settings
from app.core.exceptions import EmbeddingNotConfiguredError
from app.core.logging import get_logger
from app.db.session import engine
from app.schemas.document import DocumentChunkItem
from app.services import embedding_service

logger = get_logger(__name__)

_DOCUMENT_ID_KEY = "document_id"
_CHUNK_INDEX_KEY = "chunk_index"


class _StorageOnlyEmbeddings(Embeddings):
    """占位 Embeddings。

    本服务只负责把「已算好的向量」存取进 PGVector，向量化本身由
    ``embedding_service`` 完成，因此这里不需要真正可用的 embedding 客户端。
    未配置密钥时用它构造 store，保证删除 / 预览等操作不受影响。
    """

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingNotConfiguredError()

    def embed_query(self, text: str) -> list[float]:
        raise EmbeddingNotConfiguredError()

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingNotConfiguredError()

    async def aembed_query(self, text: str) -> list[float]:
        raise EmbeddingNotConfiguredError()


@lru_cache
def get_store() -> PGVector:
    """返回绑定应用异步引擎的 PGVector 实例（进程内复用）。"""
    embeddings: Embeddings = (
        embedding_service.build_embeddings()
        if embedding_service.is_configured()
        else _StorageOnlyEmbeddings()
    )
    return PGVector(
        embeddings=embeddings,
        connection=engine,
        embedding_length=settings.embedding_dim,
        collection_name=settings.pgvector_collection_name,
        async_mode=True,
        # vector 扩展已由初始化脚本 / 迁移创建，这里不重复申请权限
        create_extension=False,
    )


def chunk_id(document_id: UUID, chunk_index: int) -> str:
    """分块在 ``langchain_pg_embedding`` 中的主键（确定性，便于 upsert 与定位）。"""
    return f"{document_id}:{chunk_index}"


async def add_document_chunks(
    *,
    document_id: UUID,
    knowledge_base_id: UUID | None,
    user_id: UUID,
    original_filename: str,
    chunks: list[str],
) -> int:
    """向量化分块并写入 PGVector，返回写入条数。"""
    if not chunks:
        return 0

    vectors = await embedding_service.embed_texts(chunks)
    store = get_store()
    ids = [chunk_id(document_id, index) for index in range(len(chunks))]
    metadatas = [
        {
            _DOCUMENT_ID_KEY: str(document_id),
            "knowledge_base_id": str(knowledge_base_id) if knowledge_base_id else None,
            "user_id": str(user_id),
            "original_filename": original_filename,
            _CHUNK_INDEX_KEY: index,
            "char_count": len(chunk),
        }
        for index, chunk in enumerate(chunks)
    ]
    await store.aadd_embeddings(
        texts=chunks,
        embeddings=vectors,
        metadatas=metadatas,
        ids=ids,
    )
    logger.info(
        "vector_chunks_stored",
        document_id=str(document_id),
        count=len(chunks),
        collection=settings.pgvector_collection_name,
    )
    return len(chunks)


async def delete_document_chunks(document_id: UUID) -> int:
    """按 ``document_id`` 删除该文档的全部分块向量，返回删除条数。"""
    store = get_store()
    # 确保表 / collection / 动态模型已初始化
    await store.acreate_collection()
    async with store.session_maker() as session:
        collection = await store.aget_collection(session)
        if collection is None:
            return 0
        stmt = delete(store.EmbeddingStore).where(
            store.EmbeddingStore.collection_id == collection.uuid,
            store.EmbeddingStore.cmetadata.contains({_DOCUMENT_ID_KEY: str(document_id)}),
        )
        result = await session.execute(stmt)
        await session.commit()
        deleted = result.rowcount or 0
    if deleted:
        logger.info("vector_chunks_deleted", document_id=str(document_id), count=deleted)
    return deleted


async def list_document_chunks(document_id: UUID) -> list[DocumentChunkItem]:
    """按分块序号升序返回文档的分块预览（不含向量本身）。"""
    store = get_store()
    await store.acreate_collection()
    async with store.session_maker() as session:
        collection = await store.aget_collection(session)
        if collection is None:
            return []
        stmt = (
            select(store.EmbeddingStore)
            .where(
                store.EmbeddingStore.collection_id == collection.uuid,
                store.EmbeddingStore.cmetadata.contains({_DOCUMENT_ID_KEY: str(document_id)}),
            )
            .order_by(cast(store.EmbeddingStore.cmetadata[_CHUNK_INDEX_KEY].astext, Integer))
        )
        rows = (await session.execute(stmt)).scalars().all()

    items: list[DocumentChunkItem] = []
    for row in rows:
        metadata = row.cmetadata or {}
        content = row.document or ""
        items.append(
            DocumentChunkItem(
                id=row.id,
                chunk_index=int(metadata.get(_CHUNK_INDEX_KEY, 0)),
                content=content,
                char_count=int(metadata.get("char_count", len(content))),
                has_embedding=row.embedding is not None,
                meta_data=metadata,
            )
        )
    return items
