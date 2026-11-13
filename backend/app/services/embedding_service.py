"""文本向量化：基于 LangChain 的 OpenAI 兼容 Embeddings 接口。

默认对接阿里云百炼（DashScope）兼容模式，模型 ``qwen3.7-text-embedding``，
密钥取自系统环境变量 ``DASHSCOPE_API_KEY``。向量维度由 ``EMBEDDING_DIM``
决定，必须与 ``langchain_pg_embedding`` 的向量列维度一致；未配置密钥时抛
:class:`EmbeddingNotConfiguredError`，由文档服务记录失败原因。

算好的向量交给 :mod:`app.services.vector_store_service` 写入 PGVector。
"""

from __future__ import annotations

from langchain_openai import OpenAIEmbeddings

from app.core.config import settings
from app.core.exceptions import DocumentProcessingError, EmbeddingNotConfiguredError
from app.core.logging import get_logger

logger = get_logger(__name__)


def is_configured() -> bool:
    """是否已配置可用的 embedding 服务。"""
    return bool(settings.dashscope_api_key)


def build_embeddings() -> OpenAIEmbeddings:
    """构造 LangChain Embeddings 客户端；未配置密钥时抛 503。"""
    if not settings.dashscope_api_key:
        raise EmbeddingNotConfiguredError()

    return OpenAIEmbeddings(
        model=settings.embedding_model,
        openai_api_key=settings.dashscope_api_key,
        openai_api_base=settings.embedding_base_url,
        chunk_size=settings.embedding_batch_size,
        # 兼容 OpenAI 协议的第三方网关：直接发送原文，避免 tiktoken 分词与下载词表
        check_embedding_ctx_length=False,
    )


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量把文本转成向量，返回顺序与入参一致。"""
    if not texts:
        return []

    embeddings = build_embeddings()
    batch_size = max(1, settings.embedding_batch_size)

    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        batch_vectors = await embeddings.aembed_documents(batch)
        vectors.extend(batch_vectors)

    if len(vectors) != len(texts):
        raise DocumentProcessingError(
            "Embedding 返回条数与输入不一致",
            details={"expected": len(texts), "actual": len(vectors)},
        )

    expected_dim = settings.embedding_dim
    for vector in vectors:
        if len(vector) != expected_dim:
            raise DocumentProcessingError(
                f"Embedding 维度与配置不一致：期望 {expected_dim}，实际 {len(vector)}",
                details={"expected_dim": expected_dim, "actual_dim": len(vector)},
            )

    logger.info("document_embeddings_created", count=len(vectors), model=settings.embedding_model)
    return [list(vector) for vector in vectors]
