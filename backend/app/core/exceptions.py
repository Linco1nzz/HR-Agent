"""项目自定义异常体系。

设计原则：

1. 业务代码只 ``raise`` 本模块的异常，不直接抛 ``HTTPException``；HTTP 状态码、
   统一错误响应体由 ``app.core.exception_handlers`` 负责转换。
2. 每个异常类固定 ``status_code`` + ``code`` + ``default_message``，调用方可以
   只传自定义文案，也可以只传 ``details`` 上下文。
3. 所有异常继承 :class:`AppException`，便于统一捕获、记录日志与扩展。

使用示例::

    from app.core.exceptions import ConflictError, NotFoundError

    raise NotFoundError("用户不存在", details={"user_id": user_id})
    raise ConflictError("邮箱已被注册", details={"field": "email"})
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from app.core.error_codes import ErrorCode


class AppException(Exception):
    """项目所有业务异常的共同基类。

    :param message: 面向调用方的错误说明，省略时使用类上的 ``default_message``。
    :param details: 附加上下文；4xx 原样返回，5xx 在生产环境会被隐藏。
    :param headers: 需要透传给客户端的响应头（如 401 的 ``WWW-Authenticate``）。
    """

    status_code: ClassVar[int] = 500
    code: ClassVar[ErrorCode] = ErrorCode.INTERNAL_ERROR
    default_message: ClassVar[str] = "服务器内部错误"
    #: 未经调用方覆盖时默认透传的响应头（如 401 的 ``WWW-Authenticate``）
    default_headers: ClassVar[Mapping[str, str] | None] = None

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details = details
        resolved_headers = headers or self.default_headers
        self.headers = dict(resolved_headers) if resolved_headers else None
        super().__init__(self.message)

    def __repr__(self) -> str:
        return (
            f"<{type(self).__name__} code={self.code.value} "
            f"status_code={self.status_code} message={self.message!r}>"
        )


# ---------------------------------------------------------------------------
# 4xx：调用方能修正的错误
# ---------------------------------------------------------------------------
class BadRequestError(AppException):
    """400：请求格式或参数取值不合法。"""

    status_code = 400
    code = ErrorCode.BAD_REQUEST
    default_message = "请求参数有误"


class UnauthorizedError(AppException):
    """401：未提供凭证、凭证无效或已过期。"""

    status_code = 401
    code = ErrorCode.UNAUTHORIZED
    default_message = "未认证或登录已过期"
    #: RFC 7235：携带 Bearer 令牌的 401 响应应声明认证方案
    default_headers: ClassVar[Mapping[str, str] | None] = {"WWW-Authenticate": "Bearer"}


class ForbiddenError(AppException):
    """403：已认证但没有操作该资源的权限。"""

    status_code = 403
    code = ErrorCode.FORBIDDEN
    default_message = "没有访问该资源的权限"


class NotFoundError(AppException):
    """404：请求的资源不存在。"""

    status_code = 404
    code = ErrorCode.NOT_FOUND
    default_message = "请求的资源不存在"


class ConflictError(AppException):
    """409：资源状态冲突（重复创建、并发修改等）。"""

    status_code = 409
    code = ErrorCode.CONFLICT
    default_message = "资源状态冲突"


class UnprocessableEntityError(AppException):
    """422：语义上无法处理的请求（如业务规则校验失败）。"""

    status_code = 422
    code = ErrorCode.UNPROCESSABLE_ENTITY
    default_message = "请求参数无法处理"


class RateLimitError(AppException):
    """429：触发限流，稍后可重试。"""

    status_code = 429
    code = ErrorCode.TOO_MANY_REQUESTS
    default_message = "请求过于频繁，请稍后重试"


# ---------------------------------------------------------------------------
# 认证 / 授权：401 / 403 的细分场景，便于前端按错误码做不同提示
# ---------------------------------------------------------------------------
class InvalidCredentialsError(UnauthorizedError):
    """401：用户名或密码错误（不区分账号是否存在，避免账号枚举）。"""

    code = ErrorCode.INVALID_CREDENTIALS
    default_message = "用户名或密码错误"


class InvalidTokenError(UnauthorizedError):
    """401：未携带令牌、令牌格式 / 签名非法，或令牌对应用户已失效。"""

    code = ErrorCode.INVALID_TOKEN
    default_message = "登录凭证无效，请重新登录"


class TokenExpiredError(UnauthorizedError):
    """401：令牌已过期，需要重新登录。"""

    code = ErrorCode.TOKEN_EXPIRED
    default_message = "登录已过期，请重新登录"


class AccountDisabledError(ForbiddenError):
    """403：账号存在但已被停用。"""

    code = ErrorCode.ACCOUNT_DISABLED
    default_message = "账号已被停用，请联系管理员"


# ---------------------------------------------------------------------------
# 5xx：服务端或依赖方的问题
# ---------------------------------------------------------------------------
class InternalError(AppException):
    """500：已知但无法自动恢复的服务端错误。"""

    status_code = 500
    code = ErrorCode.INTERNAL_ERROR
    default_message = "服务器内部错误"


class DatabaseError(AppException):
    """500：数据库操作失败。

    业务层捕获 SQLAlchemy 异常后如需附加业务上下文，可转换成该异常再抛出；
    未捕获的 SQLAlchemy 异常由全局处理器兜底。
    """

    status_code = 500
    code = ErrorCode.DATABASE_ERROR
    default_message = "数据库操作失败"


class ExternalServiceError(AppException):
    """502：第三方服务调用失败（LLM、对象存储等）。"""

    status_code = 502
    code = ErrorCode.EXTERNAL_SERVICE_ERROR
    default_message = "外部服务调用失败"


class ServiceUnavailableError(AppException):
    """503：服务或依赖暂时不可用。"""

    status_code = 503
    code = ErrorCode.SERVICE_UNAVAILABLE
    default_message = "服务暂时不可用"
