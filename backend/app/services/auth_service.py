"""认证业务逻辑：凭据校验、令牌签发、令牌换用户与退出记录。

接口层只负责 HTTP 细节，认证规则集中在这里，便于被其他入口
（如 WebSocket、后台任务）复用。
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AccountDisabledError,
    InvalidCredentialsError,
    InvalidTokenError,
)
from app.core.logging import get_logger
from app.core.security import (
    access_token_expires_in,
    create_access_token,
    decode_access_token,
    verify_password_or_dummy,
)
from app.db.models import User
from app.schemas.auth import TokenResponse
from app.schemas.user import UserRead
from app.services import user_service

logger = get_logger(__name__)


async def authenticate_user(db: AsyncSession, identifier: str, password: str) -> User:
    """校验账号密码，成功时更新最后登录时间并提交事务。

    账号不存在与密码错误都抛出 :class:`~app.core.exceptions.InvalidCredentialsError`，
    避免账号枚举；账号被停用时抛出 :class:`~app.core.exceptions.AccountDisabledError`。
    """
    user = await user_service.get_user_by_identifier(db, identifier)

    if user is None:
        # 账号不存在时也执行一次哈希校验，避免通过响应时间判断账号是否存在
        verify_password_or_dummy(password, None)
        logger.warning("login_failed", reason="unknown_account", identifier=identifier)
        raise InvalidCredentialsError()

    if not verify_password_or_dummy(password, user.hashed_password):
        logger.warning(
            "login_failed",
            reason="wrong_password",
            identifier=identifier,
            user_id=str(user.id),
        )
        raise InvalidCredentialsError()

    if not user.is_active:
        logger.warning(
            "login_failed",
            reason="account_disabled",
            identifier=identifier,
            user_id=str(user.id),
        )
        raise AccountDisabledError()

    last_login = datetime.now(UTC)
    user.last_login = last_login
    await db.commit()

    logger.info(
        "login_succeeded",
        user_id=str(user.id),
        username=user.username,
        last_login=last_login.isoformat(),
    )
    return user


def issue_access_token(user: User) -> TokenResponse:
    """为用户签发访问令牌，并组装登录响应。"""
    return TokenResponse(
        access_token=create_access_token(user.id),
        expires_in=access_token_expires_in(),
        user=UserRead.model_validate(user),
    )


async def login(db: AsyncSession, identifier: str, password: str) -> TokenResponse:
    """登录：校验凭据后签发访问令牌。"""
    user = await authenticate_user(db, identifier, password)
    return issue_access_token(user)


async def resolve_user_from_token(db: AsyncSession, token: str) -> User:
    """把访问令牌换成当前用户，并校验用户存在且账号处于启用状态。"""
    payload = decode_access_token(token)
    user = await user_service.get_user_by_id(db, UUID(payload.sub))
    if user is None:
        raise InvalidTokenError("令牌对应的用户不存在或已被删除")
    if not user.is_active:
        raise AccountDisabledError()
    return user


def record_logout(user: User) -> None:
    """记录退出事件；JWT 无状态，服务端不保存会话。"""
    logger.info("logout", user_id=str(user.id), username=user.username)
