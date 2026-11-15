"""候选片段重排序：阿里云百炼原生 text-rerank 接口。

请求 ``settings.rerank_base_url``（复用 ``DASHSCOPE_API_KEY``），按返回的
``index`` 映射回候选并附 ``relevance_score``。未配置密钥、请求失败或超时
时只记 warning，回退为按 RRF 得分取前 ``settings.qa_top_k``，不抛错。
"""

from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.services.kb_retrieval_service import RetrievedChunk

logger = get_logger(__name__)


async def rerank(
    query: str,
    candidates: list[RetrievedChunk],
) -> list[tuple[RetrievedChunk, float]]:
    """重排候选片段，返回 (候选, 得分) 列表；得分优先用 rerank 相关性。"""
    top_k = settings.qa_top_k
    if not candidates:
        return []

    fallback = [
        (chunk, chunk.rrf_score)
        for chunk in sorted(candidates, key=lambda item: (-item.rrf_score, item.chunk_id))[:top_k]
    ]
    if not settings.dashscope_api_key:
        logger.warning("rerank_skipped", reason="DASHSCOPE_API_KEY 未配置，回退 RRF 排序")
        return fallback

    payload = {
        "model": settings.rerank_model,
        "input": {
            "query": query,
            "documents": [chunk.content[: settings.rerank_max_doc_chars] for chunk in candidates],
        },
        "parameters": {"top_n": min(top_k, len(candidates)), "return_documents": False},
    }
    try:
        async with httpx.AsyncClient(timeout=settings.rerank_timeout_seconds) as client:
            response = await client.post(
                settings.rerank_base_url,
                json=payload,
                headers={"Authorization": f"Bearer {settings.dashscope_api_key}"},
            )
            response.raise_for_status()
            data = response.json()
        results = data["output"]["results"]
        ranked: list[tuple[RetrievedChunk, float]] = []
        for item in results:
            index = int(item["index"])
            if 0 <= index < len(candidates):
                ranked.append((candidates[index], float(item["relevance_score"])))
        if not ranked:
            raise ValueError("rerank 返回结果为空")
        ranked.sort(key=lambda pair: pair[1], reverse=True)
        logger.info("rerank_finished", candidates=len(candidates), kept=len(ranked[:top_k]))
        return ranked[:top_k]
    except Exception as exc:  # noqa: BLE001 - rerank 失败回退 RRF，不阻断问答
        logger.warning("rerank_failed_fallback_rrf", error=str(exc))
        return fallback
