"""密码哈希与 JWT 访问令牌工具。

密码部分使用 ``argon2-cffi`` 的 :class:`~argon2.PasswordHasher`，默认算法为
Argon2id（内存困难型 KDF）。参数通过 ``settings.argon2_*`` 配置，默认值为
32 MiB 内存 / 2 次迭代 / 2 并行度，低于 argon2-cffi 的默认值；与 bcrypt
不同，Argon2 没有 72 字节的密码长度限制。

令牌部分使用 PyJWT 签发 / 校验访问令牌（默认 HS256）。载荷包含：

* ``sub``：用户 ID（UUID 字符串）
* ``iat`` / ``exp``：签发 / 过期时间戳（UTC 秒）
* ``jti``：令牌唯一标识
* ``type``：令牌类型，固定为 ``access``（便于将来区分刷新令牌等类型）

密钥与有效期分别取自 ``settings.jwt_secret`` 与
``settings.access_token_expire_minutes``。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, Literal
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from pydantic import BaseModel, ConfigDict

from app.core.config import settings
from app.core.exceptions import InvalidTokenError, TokenExpiredError

#: 访问令牌的 ``type`` 声明值
ACCESS_TOKEN_TYPE: Literal["access"] = "access"

#: 校验 ``iat`` / ``exp`` 时允许的时钟偏差（秒），避免多实例间时钟微差导致误判
_CLOCK_LEEWAY_SECONDS = 5

_password_hasher = PasswordHasher(
    time_cost=settings.argon2_time_cost,
    memory_cost=settings.argon2_memory_cost,
    parallelism=settings.argon2_parallelism,
)


# ---------------------------------------------------------------------------
# 密码哈希
# ---------------------------------------------------------------------------
def get_password_hash(password: str) -> str:
    """生成 Argon2id 密码哈希，供写入数据库。"""
    return _password_hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验明文密码与数据库中的哈希是否匹配。"""
    try:
        return _password_hasher.verify(hashed_password, plain_password)
    except (VerificationError, InvalidHashError):
        # 密码不匹配，或哈希为空/格式非法时，均按校验失败处理
        return False


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    """账号不存在时用于填充哈希校验耗时，避免通过响应时间枚举账号。"""
    return get_password_hash("hr-agent-dummy-password")


def verify_password_or_dummy(plain_password: str, hashed_password: str | None) -> bool:
    """校验密码；``hashed_password`` 为空时仍执行一次哈希运算并返回 ``False``。"""
    if not hashed_password:
        verify_password(plain_password, _dummy_password_hash())
        return False
    return verify_password(plain_password, hashed_password)


# ---------------------------------------------------------------------------
# JWT 访问令牌
# ---------------------------------------------------------------------------
class TokenPayload(BaseModel):
    """校验通过的访问令牌载荷。"""

    model_config = ConfigDict(frozen=True)

    sub: str
    exp: datetime
    iat: datetime
    jti: str
    type: Literal["access"] = ACCESS_TOKEN_TYPE


def access_token_expires_in() -> int:
    """访问令牌有效期（秒），供登录响应返回给客户端。"""
    return settings.access_token_expire_minutes * 60


def create_access_token(subject: str | UUID, *, expires_delta: timedelta | None = None) -> str:
    """签发访问令牌。

    :param subject: 令牌主体，通常是用户 ID，写入 ``sub`` 声明。
    :param expires_delta: 自定义有效期；省略时使用
        ``settings.access_token_expire_minutes``。
    """
    now = datetime.now(UTC)
    expires_at = now + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": uuid.uuid4().hex,
        "type": ACCESS_TOKEN_TYPE,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> TokenPayload:
    """校验并解析访问令牌。

    签名错误、令牌过期、缺少必需声明或 ``sub`` 不是合法 UUID 时，
    分别抛出 :class:`~app.core.exceptions.InvalidTokenError` /
    :class:`~app.core.exceptions.TokenExpiredError`，由全局异常处理器
    转换成统一的 401 响应。
    """
    try:
        raw = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp", "iat", "jti"]},
            leeway=timedelta(seconds=_CLOCK_LEEWAY_SECONDS),
        )
    except jwt.ExpiredSignatureError:
        raise TokenExpiredError() from None
    except jwt.InvalidTokenError:
        raise InvalidTokenError() from None

    if raw.get("type") != ACCESS_TOKEN_TYPE:
        raise InvalidTokenError("令牌类型不正确，请重新登录")

    try:
        subject = str(raw["sub"])
        UUID(subject)  # sub 必须是合法的用户 ID
        return TokenPayload(
            sub=subject,
            iat=datetime.fromtimestamp(int(raw["iat"]), tz=UTC),
            exp=datetime.fromtimestamp(int(raw["exp"]), tz=UTC),
            jti=str(raw["jti"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidTokenError() from exc
