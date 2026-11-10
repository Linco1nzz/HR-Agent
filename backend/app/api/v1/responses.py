"""接口层共用的响应构造。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi.responses import StreamingResponse

_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def sse_response(events: AsyncIterator[bytes]) -> StreamingResponse:
    """构造统一的 SSE 流式响应，避免每个生成接口重复设置响应头。"""
    return StreamingResponse(events, media_type="text/event-stream", headers=_SSE_HEADERS)
