"""知识库问答的混合检索：向量召回 + 关键词召回，RRF 融合去重。

两路召回都限定在会话绑定的知识库内（``cmetadata.knowledge_base_id``）：

* 向量路：PGVector ``asimilarity_search_with_score``（余弦距离），
  ``similarity = 1 - distance``，低于 ``settings.qa_min_similarity`` 丢弃；
* 关键词路：直接 SQL 查 ``langchain_pg_embedding``，按命中关键词个数排序。

融合采用 Reciprocal Rank Fusion（k=60），按 chunk_id 去重，最多保留
``settings.qa_recall_k`` 个候选交给 rerank。任一路失败只记日志并降级，
不阻断问答。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import reduce
from operator import add
from uuid import UUID

from langchain_core.documents import Document as LCDocument
from sqlalchemy import case, or_, select

from app.core.config import settings
from app.core.logging import get_logger
from app.services import embedding_service, vector_store_service

logger = get_logger(__name__)

#: RRF 平滑常数（经验值）
RRF_K = 60


@dataclass(slots=True)
class RetrievedChunk:
    """一个候选分块及其两路得分。"""

    chunk_id: str
    document_id: str
    document_name: str
    knowledge_base_id: str
    chunk_index: int
    content: str
    #: 向量路余弦相似度（1 - 余弦距离）
    vector_score: float | None = None
    #: 关键词路命中的关键词个数
    keyword_score: float | None = None
    #: RRF 融合得分
    rrf_score: float = 0.0


async def retrieve(
    query: str,
    keywords: list[str],
    knowledge_base_ids: list[UUID],
) -> list[RetrievedChunk]:
    """混合检索入口；未绑定知识库或无结果时返回空列表。"""
    if not knowledge_base_ids:
        return []
    kb_ids = [str(kb_id) for kb_id in knowledge_base_ids]
    vector_chunks = await _vector_recall(query, kb_ids)
    keyword_chunks = await _keyword_recall(keywords, kb_ids)
    merged = merge_rrf(vector_chunks, keyword_chunks)
    logger.info(
        "qa_retrieval_finished",
        vector_hits=len(vector_chunks),
        keyword_hits=len(keyword_chunks),
        merged=len(merged),
    )
    return merged


def merge_rrf(
    vector_chunks: list[RetrievedChunk],
    keyword_chunks: list[RetrievedChunk],
    *,
    limit: int | None = None,
) -> list[RetrievedChunk]:
    """RRF 融合两路排名：score = Σ 1 / (RRF_K + rank)，按 chunk_id 去重。"""
    merged: dict[str, RetrievedChunk] = {}
    for ranked in (vector_chunks, keyword_chunks):
        for rank, chunk in enumerate(ranked, start=1):
            existing = merged.get(chunk.chunk_id)
            if existing is None:
                existing = replace(chunk)
                merged[chunk.chunk_id] = existing
            if chunk.vector_score is not None:
                existing.vector_score = chunk.vector_score
            if chunk.keyword_score is not None:
                existing.keyword_score = chunk.keyword_score
            existing.rrf_score += 1.0 / (RRF_K + rank)
    ordered = sorted(merged.values(), key=lambda item: (-item.rrf_score, item.chunk_id))
    cap = settings.qa_recall_k if limit is None else limit
    return ordered[:cap]


# ---------------------------------------------------------------------------
# 向量路
# ---------------------------------------------------------------------------
async def _vector_recall(query: str, kb_ids: list[str]) -> list[RetrievedChunk]:
    """PGVector 余弦相似度召回；未配置 embedding 或查询失败时降级为空。"""
    if not embedding_service.is_configured():
        logger.warning("qa_vector_recall_skipped", reason="DASHSCOPE_API_KEY 未配置")
        return []
    store = vector_store_service.get_store()
    try:
        results = await store.asimilarity_search_with_score(
            query,
            k=settings.qa_recall_k,
            filter={"knowledge_base_id": {"$in": kb_ids}},
        )
    except Exception as exc:  # noqa: BLE001 - 单路失败不应阻断问答
        logger.warning("qa_vector_recall_failed", error=str(exc))
        return []

    chunks: list[RetrievedChunk] = []
    for doc, distance in results:
        similarity = 1.0 - float(distance)
        if similarity < settings.qa_min_similarity:
            continue
        chunks.append(_chunk_from_metadata(doc, vector_score=similarity))
    return chunks


def _chunk_from_metadata(
    doc: LCDocument,
    *,
    vector_score: float | None = None,
    keyword_score: float | None = None,
) -> RetrievedChunk:
    metadata = doc.metadata or {}
    document_id = str(metadata.get("document_id", ""))
    chunk_index = int(metadata.get("chunk_index", 0))
    return RetrievedChunk(
        chunk_id=doc.id or f"{document_id}:{chunk_index}",
        document_id=document_id,
        document_name=str(metadata.get("original_filename", "")),
        knowledge_base_id=str(metadata.get("knowledge_base_id", "")),
        chunk_index=chunk_index,
        content=doc.page_content,
        vector_score=vector_score,
        keyword_score=keyword_score,
    )


# ---------------------------------------------------------------------------
# 关键词路
# ---------------------------------------------------------------------------
async def _keyword_recall(keywords: list[str], kb_ids: list[str]) -> list[RetrievedChunk]:
    """SQL ILIKE 召回：命中任一关键词即入选，按命中个数降序。"""
    terms = [term.strip() for term in keywords if term and term.strip()]
    if not terms:
        return []
    store = vector_store_service.get_store()
    try:
        await store.acreate_collection()
        async with store.session_maker() as session:
            collection = await store.aget_collection(session)
            if collection is None:
                return []
            embedding_store = store.EmbeddingStore
            hit_count = reduce(
                add,
                (case((embedding_store.document.ilike(f"%{term}%"), 1), else_=0) for term in terms),
            )
            stmt = (
                select(embedding_store, hit_count.label("keyword_score"))
                .where(
                    embedding_store.collection_id == collection.uuid,
                    embedding_store.cmetadata["knowledge_base_id"].astext.in_(kb_ids),
                    or_(*(embedding_store.document.ilike(f"%{term}%") for term in terms)),
                )
                .order_by(hit_count.desc())
                .limit(settings.qa_recall_k)
            )
            rows = (await session.execute(stmt)).all()
    except Exception as exc:  # noqa: BLE001 - 单路失败不应阻断问答
        logger.warning("qa_keyword_recall_failed", error=str(exc))
        return []

    chunks: list[RetrievedChunk] = []
    for row in rows:
        record = row[0]
        doc = LCDocument(
            id=str(record.id),
            page_content=record.document or "",
            metadata=record.cmetadata or {},
        )
        chunks.append(_chunk_from_metadata(doc, keyword_score=float(row[1])))
    return chunks
