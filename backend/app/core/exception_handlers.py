"""全局异常处理器：把各类异常转换成统一的错误响应。

覆盖范围与优先级（从具体到宽泛）：

1. 项目自定义异常（:class:`~app.core.exceptions.AppException` 及其子类）
2. FastAPI / Starlette 内置异常（``HTTPException``、``WebSocketException``）
3. 请求参数校验（``RequestValidationError``）与响应校验（``ResponseValidationError``）
4. SQLAlchemy 数据库异常（完整性约束、连接失败、超时、查询结果异常等）
5. 其余未知异常（兜底 500，只记录日志、不向客户端泄露内部细节）

注册入口为 :func:`register_exception_handlers`，由 ``app.main.create_app`` 调用。
"""

from __future__ import annotations

import http
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import FastAPI
from fastapi.exceptions import (
    RequestValidationError,
    ResponseValidationError,
    WebSocketRequestValidationError,
)
from fastapi.utils import is_body_allowed_for_status_code
from sqlalchemy.exc import (
    IntegrityError,
    MultipleResultsFound,
    NoResultFound,
    OperationalError,
    SQLAlchemyError,
)
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.exceptions import WebSocketException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.status import WS_1008_POLICY_VIOLATION, WS_1011_INTERNAL_ERROR
from starlette.types import ExceptionHandler
from starlette.websockets import WebSocket

from app.core.config import settings
from app.core.error_codes import ErrorCode, error_code_for_status
from app.core.exceptions import AppException
from app.core.logging import get_logger
from app.schemas.error import ErrorResponse, FieldError

logger = get_logger(__name__)

#: 响应头中的请求追踪 ID（与 RequestContextMiddleware 保持一致）
REQUEST_ID_HEADER = "X-Request-ID"

#: 调试信息中异常文本的最大长度，避免日志/响应体过大
_MAX_DEBUG_REASON_LENGTH = 500

#: 框架默认的英文状态短语 → 中文默认文案（仅在 detail 未自定义时使用）
_DEFAULT_HTTP_MESSAGES: dict[int, str] = {
    400: "请求参数有误",
    401: "未认证或登录已过期",
    403: "没有访问该资源的权限",
    404: "请求的资源不存在",
    405: "请求方法不被允许",
    406: "无法满足请求的响应格式",
    409: "资源状态冲突",
    413: "请求体过大",
    415: "不支持的媒体类型",
    422: "请求参数校验失败",
    429: "请求过于频繁，请稍后重试",
    500: "服务器内部错误",
    501: "服务器不支持该请求",
    502: "外部服务调用失败",
    503: "服务暂时不可用",
    504: "网关响应超时",
}


# ---------------------------------------------------------------------------
# 响应与日志辅助
# ---------------------------------------------------------------------------
def _get_request_id(request: Request) -> str | None:
    """读取 RequestContextMiddleware 写入的请求 ID（未安装中间件时为 None）。"""
    return getattr(request.state, "request_id", None)


def _request_context(conn: Request | WebSocket) -> dict[str, Any]:
    """结构化日志公共字段（HTTP 与 WebSocket 通用）。"""
    return {
        "request_id": getattr(conn.state, "request_id", None),
        "method": getattr(conn, "method", None) or "WEBSOCKET",
        "path": conn.url.path,
        "client": conn.client.host if conn.client else None,
    }


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: ErrorCode,
    message: str,
    details: dict[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """构造统一错误响应，并补齐 ``X-Request-ID`` 响应头。"""
    request_id = _get_request_id(request)
    payload = ErrorResponse(
        code=code.value,
        message=message,
        details=details,
        request_id=request_id,
        timestamp=datetime.now(UTC),
    ).model_dump(mode="json", exclude_none=True)

    response_headers: dict[str, str] = dict(headers or {})
    if request_id:
        response_headers.setdefault(REQUEST_ID_HEADER, request_id)
    return JSONResponse(status_code=status_code, content=payload, headers=response_headers)


def _status_phrase(status_code: int) -> str:
    """HTTP 状态码的英文标准短语；未知状态码返回空串。"""
    try:
        return http.HTTPStatus(status_code).phrase
    except ValueError:
        return ""


def _http_exception_message(exc: StarletteHTTPException) -> str:
    """显式自定义的 detail 原样返回，框架默认英文短语替换为中文默认文案。"""
    detail = exc.detail
    if isinstance(detail, str) and detail and detail != _status_phrase(exc.status_code):
        return detail
    return _DEFAULT_HTTP_MESSAGES.get(exc.status_code, "请求失败")


def _field_error(error: Mapping[str, Any]) -> dict[str, Any]:
    """把 Pydantic 的 error dict 裁剪成对外安全的字段错误。

    只保留字段路径、说明与类型：``input`` / ``ctx`` 可能包含密码、原文等敏感数据，
    不进入响应体。
    """
    location = error.get("loc") or ()
    field = ".".join(str(part) for part in location) or "request"
    return FieldError(
        field=field,
        message=str(error.get("msg") or "参数不合法"),
        type=str(error["type"]) if error.get("type") else None,
    ).model_dump(exclude_none=True)


def _field_errors(
    exc: RequestValidationError | ResponseValidationError,
) -> list[dict[str, Any]]:
    return [_field_error(error) for error in exc.errors()]


def _debug_details(exc: Exception, **extra: Any) -> dict[str, Any] | None:
    """非生产环境附带异常摘要，生产环境不暴露任何内部细节。"""
    if settings.is_production:
        return None
    return {
        "exception": type(exc).__name__,
        "reason": str(exc)[:_MAX_DEBUG_REASON_LENGTH],
        **{key: value for key, value in extra.items() if value is not None},
    }


def _constraint_name(exc: IntegrityError) -> str | None:
    """尽力从驱动异常中取出约束名（psycopg 在 diag，asyncpg 在异常属性上）。"""
    orig: Any = exc.orig
    if orig is None:
        return None

    diag = getattr(orig, "diag", None)
    candidates = [
        getattr(diag, "constraint_name", None),
        getattr(orig, "constraint_name", None),
    ]
    cause = getattr(orig, "__cause__", None)
    if cause is not None:
        candidates.append(getattr(cause, "constraint_name", None))

    for candidate in candidates:
        if candidate:
            return str(candidate)
    return None


# ---------------------------------------------------------------------------
# 1) 项目自定义异常
# ---------------------------------------------------------------------------
def _truncate_ws_reason(message: str, max_bytes: int = 120) -> str:
    """WebSocket close reason 上限 123 字节，按 UTF-8 边界安全截断。"""
    encoded = message.encode("utf-8")
    if len(encoded) <= max_bytes:
        return message
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


async def _close_websocket_with_app_exception(websocket: WebSocket, exc: AppException) -> None:
    """WebSocket 场景无法返回 JSON，以 close code + reason 传回错误信息。"""
    close_code = WS_1008_POLICY_VIOLATION if exc.status_code < 500 else WS_1011_INTERNAL_ERROR
    log = logger.warning if exc.status_code < 500 else logger.error
    log(
        "app_exception_websocket",
        code=exc.code.value,
        status_code=exc.status_code,
        details=exc.details,
        **_request_context(websocket),
    )
    await websocket.close(code=close_code, reason=_truncate_ws_reason(exc.message))


async def app_exception_handler(conn: Request | WebSocket, exc: AppException) -> Response | None:
    """4xx 记 warning，5xx 记 error 并附堆栈；WebSocket 连接改为关闭连接。"""
    if isinstance(conn, WebSocket):
        await _close_websocket_with_app_exception(conn, exc)
        return None
    request = conn

    log_fields = {
        "code": exc.code.value,
        "status_code": exc.status_code,
        **_request_context(request),
    }
    if exc.status_code >= 500:
        logger.error("app_exception", exc_info=exc, details=exc.details, **log_fields)
    else:
        logger.warning("app_exception", details=exc.details, **log_fields)

    # 5xx 的 details 可能包含内部信息，生产环境只返回文案
    details = exc.details
    if settings.is_production and exc.status_code >= 500:
        details = None

    return _error_response(
        request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=details,
        headers=exc.headers,
    )


# ---------------------------------------------------------------------------
# 2) FastAPI / Starlette 内置异常
# ---------------------------------------------------------------------------
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
    """保留状态码与响应头（如 401 的 WWW-Authenticate），统一响应体。"""
    # 204 / 304 等状态码不允许带响应体
    if not is_body_allowed_for_status_code(exc.status_code):
        return Response(status_code=exc.status_code, headers=exc.headers)

    code = error_code_for_status(exc.status_code)
    message = _http_exception_message(exc)
    details = None if isinstance(exc.detail, str) else {"detail": exc.detail}

    log = logger.warning if exc.status_code < 500 else logger.error
    log(
        "http_exception",
        code=code.value,
        status_code=exc.status_code,
        detail=exc.detail,
        **_request_context(request),
    )
    return _error_response(
        request,
        status_code=exc.status_code,
        code=code,
        message=message,
        details=details,
        headers=exc.headers,
    )


async def websocket_exception_handler(websocket: WebSocket, exc: WebSocketException) -> None:
    """按 WebSocketException 指定的 close code 关闭连接，并记录日志。"""
    logger.warning(
        "websocket_exception",
        code=exc.code,
        reason=exc.reason,
        path=websocket.url.path,
        request_id=getattr(websocket.state, "request_id", None),
    )
    await websocket.close(code=exc.code, reason=exc.reason)


# ---------------------------------------------------------------------------
# 3) 请求 / 响应校验
# ---------------------------------------------------------------------------
async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """请求参数校验失败：返回字段级错误明细。"""
    errors = _field_errors(exc)
    logger.warning(
        "request_validation_failed",
        error_count=len(errors),
        errors=errors,
        **_request_context(request),
    )
    return _error_response(
        request,
        status_code=422,
        code=ErrorCode.VALIDATION_ERROR,
        message="请求参数校验失败",
        details={"errors": errors},
    )


async def response_validation_exception_handler(
    request: Request, exc: ResponseValidationError
) -> JSONResponse:
    """响应数据不符合 response_model：属于服务端问题，不向客户端暴露字段明细。"""
    errors = _field_errors(exc)
    logger.error(
        "response_validation_failed",
        errors=errors,
        exc_info=exc,
        **_request_context(request),
    )
    return _error_response(
        request,
        status_code=500,
        code=ErrorCode.RESPONSE_VALIDATION_ERROR,
        message="服务器响应数据校验失败",
        details=None if settings.is_production else {"errors": errors},
    )


async def websocket_validation_exception_handler(
    websocket: WebSocket, exc: WebSocketRequestValidationError
) -> None:
    """WebSocket 握手参数校验失败：以 1008（策略违规）关闭连接。"""
    logger.warning(
        "websocket_validation_failed",
        error_count=len(exc.errors()),
        path=websocket.url.path,
        request_id=getattr(websocket.state, "request_id", None),
    )
    await websocket.close(code=WS_1008_POLICY_VIOLATION, reason="请求参数校验失败")


# ---------------------------------------------------------------------------
# 4) SQLAlchemy 数据库异常
# ---------------------------------------------------------------------------
async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    """唯一约束 / 外键 / 非空等完整性约束冲突 → 409。"""
    constraint = _constraint_name(exc)
    logger.warning(
        "database_integrity_error",
        constraint=constraint,
        **_request_context(request),
    )
    return _error_response(
        request,
        status_code=409,
        code=ErrorCode.DATABASE_CONFLICT,
        message="数据冲突：违反唯一性或关联约束",
        details=_debug_details(exc, constraint=constraint),
    )


async def operational_error_handler(request: Request, exc: OperationalError) -> JSONResponse:
    """连接失败、连接中断、数据库不可用 → 503。"""
    logger.error("database_operational_error", exc_info=exc, **_request_context(request))
    return _error_response(
        request,
        status_code=503,
        code=ErrorCode.DATABASE_UNAVAILABLE,
        message="数据库暂时不可用，请稍后重试",
        details=_debug_details(exc),
    )


async def database_timeout_error_handler(
    request: Request, exc: SQLAlchemyTimeoutError
) -> JSONResponse:
    """连接池获取超时 → 503。"""
    logger.error("database_timeout", exc_info=exc, **_request_context(request))
    return _error_response(
        request,
        status_code=503,
        code=ErrorCode.DATABASE_TIMEOUT,
        message="数据库操作超时，请稍后重试",
        details=_debug_details(exc),
    )


async def no_result_found_handler(request: Request, exc: NoResultFound) -> JSONResponse:
    """``.one()`` / ``scalar_one()`` 未查到数据 → 404。"""
    logger.warning("database_no_result", **_request_context(request))
    return _error_response(
        request,
        status_code=404,
        code=ErrorCode.NOT_FOUND,
        message="查询的数据不存在",
    )


async def multiple_results_found_handler(
    request: Request, exc: MultipleResultsFound
) -> JSONResponse:
    """期望唯一结果却查出多条：属于代码/数据问题 → 500。"""
    logger.error("database_multiple_results", exc_info=exc, **_request_context(request))
    return _error_response(
        request,
        status_code=500,
        code=ErrorCode.DATABASE_ERROR,
        message="查询结果不唯一",
        details=_debug_details(exc),
    )


async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    """其余 SQLAlchemy 异常（如 SQL 语法、会话状态错误）→ 500。"""
    logger.error("database_error", exc_info=exc, **_request_context(request))
    return _error_response(
        request,
        status_code=500,
        code=ErrorCode.DATABASE_ERROR,
        message="数据库操作失败",
        details=_debug_details(exc),
    )


# ---------------------------------------------------------------------------
# 5) 未知异常兜底
# ---------------------------------------------------------------------------
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """未预期异常：完整堆栈只写日志，客户端只拿到通用 500。"""
    logger.error("unhandled_exception", exc_info=exc, **_request_context(request))
    return _error_response(
        request,
        status_code=500,
        code=ErrorCode.INTERNAL_ERROR,
        message="服务器内部错误",
    )


# ---------------------------------------------------------------------------
# 注册入口
# ---------------------------------------------------------------------------
def _register(
    app: FastAPI,
    exc_class: type[Exception],
    handler: Callable[..., Any],
) -> None:
    """注册单个处理器。

    Starlette 把处理器类型声明为 ``(Request, Exception)``，而这里的处理器只接受
    具体的异常子类（注册的异常类型已保证匹配），因此显式做一次类型转换。
    """
    app.add_exception_handler(exc_class, cast(ExceptionHandler, handler))


def register_exception_handlers(app: FastAPI) -> None:
    """按“具体 → 宽泛”的顺序注册全部处理器。"""
    # 1) 项目自定义异常
    _register(app, AppException, app_exception_handler)

    # 2) FastAPI / Starlette 内置异常
    _register(app, StarletteHTTPException, http_exception_handler)
    _register(app, WebSocketException, websocket_exception_handler)
    _register(app, WebSocketRequestValidationError, websocket_validation_exception_handler)

    # 3) 请求 / 响应校验
    _register(app, RequestValidationError, request_validation_exception_handler)
    _register(app, ResponseValidationError, response_validation_exception_handler)

    # 4) SQLAlchemy：具体子类优先，最后是 SQLAlchemyError 兜底
    _register(app, IntegrityError, integrity_error_handler)
    _register(app, OperationalError, operational_error_handler)
    _register(app, SQLAlchemyTimeoutError, database_timeout_error_handler)
    _register(app, NoResultFound, no_result_found_handler)
    _register(app, MultipleResultsFound, multiple_results_found_handler)
    _register(app, SQLAlchemyError, sqlalchemy_error_handler)

    # 5) 未知异常兜底（由最外层 ServerErrorMiddleware 调用）
    _register(app, Exception, unhandled_exception_handler)
