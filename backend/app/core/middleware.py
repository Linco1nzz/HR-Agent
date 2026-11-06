"""请求上下文中间件：请求追踪 ID 与日志上下文绑定。

每个请求生成（或透传）``X-Request-ID``，并写入两处：

1. ``request.state.request_id``：异常处理器用它把错误响应、响应头与日志关联起来；
2. structlog contextvars：本请求内的日志自动带上 ``request_id`` / ``method`` / ``path``。

客户端传入合法 ``X-Request-ID`` 时原样沿用（便于网关、前端串联调用链），
非法值（过长或含特殊字符）会被忽略并重新生成。
"""

from __future__ import annotations

import re
import uuid

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: 响应头中的请求追踪 ID（与 app.core.exception_handlers 保持一致）
REQUEST_ID_HEADER = "X-Request-ID"

#: ASGI 规范中 header 名全小写
_REQUEST_ID_HEADER_KEY = b"x-request-id"

#: 允许客户端传入的 ID 形态：防止日志注入与超长值
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class RequestContextMiddleware:
    """纯 ASGI 中间件，不读取请求体，开销可忽略。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._header_key = REQUEST_ID_HEADER.lower().encode("latin-1")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        request_id = self._get_or_create_request_id(scope)
        scope.setdefault("state", {})["request_id"] = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=scope.get("method"),
            path=scope.get("path"),
        )
        try:
            await self.app(scope, receive, self._wrap_send(send, request_id))
        finally:
            # 每个请求结束时清理，避免上下文串到后续请求
            structlog.contextvars.clear_contextvars()

    def _wrap_send(self, send: Send, request_id: str) -> Send:
        """在响应头中回填 ``X-Request-ID``（已存在时不重复添加）。"""

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                if not any(key.lower() == self._header_key for key, _ in headers):
                    headers.append((self._header_key, request_id.encode("latin-1")))
                    message["headers"] = headers
            await send(message)

        return send_with_request_id

    @staticmethod
    def _get_or_create_request_id(scope: Scope) -> str:
        for key, value in scope.get("headers", []):
            if key.lower() == _REQUEST_ID_HEADER_KEY:
                candidate = value.decode("latin-1").strip()
                if _VALID_REQUEST_ID.fullmatch(candidate):
                    return candidate
                break
        return uuid.uuid4().hex
