"""统一错误码定义。

错误码与 HTTP 状态码解耦：HTTP 状态码表达“哪一类错误”，错误码给前端/调用方
提供稳定的程序可读标识（不随提示文案变化，便于前端做分支处理与国际化）。

新增业务错误码时在此追加，然后在 ``app/core/exceptions.py`` 中绑定到异常类。
"""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    """对外暴露的错误码（字符串枚举，可直接 JSON 序列化）。"""

    # --- 通用 ---
    BAD_REQUEST = "BAD_REQUEST"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    CONFLICT = "CONFLICT"
    UNPROCESSABLE_ENTITY = "UNPROCESSABLE_ENTITY"
    TOO_MANY_REQUESTS = "TOO_MANY_REQUESTS"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    HTTP_ERROR = "HTTP_ERROR"

    # --- 请求 / 响应校验 ---
    VALIDATION_ERROR = "VALIDATION_ERROR"
    RESPONSE_VALIDATION_ERROR = "RESPONSE_VALIDATION_ERROR"

    # --- 数据库 ---
    DATABASE_ERROR = "DATABASE_ERROR"
    DATABASE_CONFLICT = "DATABASE_CONFLICT"
    DATABASE_UNAVAILABLE = "DATABASE_UNAVAILABLE"
    DATABASE_TIMEOUT = "DATABASE_TIMEOUT"

    # --- 外部依赖 ---
    EXTERNAL_SERVICE_ERROR = "EXTERNAL_SERVICE_ERROR"


#: HTTP 状态码 → 默认错误码（用于没有显式错误码的 HTTPException）
STATUS_CODE_TO_ERROR_CODE: dict[int, ErrorCode] = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    409: ErrorCode.CONFLICT,
    422: ErrorCode.UNPROCESSABLE_ENTITY,
    429: ErrorCode.TOO_MANY_REQUESTS,
    500: ErrorCode.INTERNAL_ERROR,
    502: ErrorCode.EXTERNAL_SERVICE_ERROR,
    503: ErrorCode.SERVICE_UNAVAILABLE,
}


def error_code_for_status(status_code: int) -> ErrorCode:
    """把 HTTP 状态码映射为错误码，未知状态码回退到 ``HTTP_ERROR``。"""
    return STATUS_CODE_TO_ERROR_CODE.get(status_code, ErrorCode.HTTP_ERROR)
