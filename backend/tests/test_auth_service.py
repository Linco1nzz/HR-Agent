"""认证服务层单元测试（不依赖数据库）。"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from app.core.config import settings
from app.core.exceptions import (
    AccountDisabledError,
    InvalidCredentialsError,
    InvalidTokenError,
    TokenExpiredError,
)
from app.core.security import create_access_token, decode_access_token
from app.services import auth_service
from tests.fakes import TEST_PASSWORD, FakeSession, make_user


async def test_authenticate_user_success_updates_last_login() -> None:
    user = make_user()
    session = FakeSession(user)

    authenticated = await auth_service.authenticate_user(session, "testuser", TEST_PASSWORD)

    assert authenticated is user
    assert session.commit_count == 1
    assert user.last_login is not None


async def test_authenticate_user_unknown_account() -> None:
    session = FakeSession(None)

    with pytest.raises(InvalidCredentialsError):
        await auth_service.authenticate_user(session, "nobody", TEST_PASSWORD)

    assert session.commit_count == 0


async def test_authenticate_user_wrong_password() -> None:
    session = FakeSession(make_user())

    with pytest.raises(InvalidCredentialsError):
        await auth_service.authenticate_user(session, "testuser", "wrong-password")

    assert session.commit_count == 0


async def test_authenticate_user_disabled_account() -> None:
    session = FakeSession(make_user(is_active=False))

    with pytest.raises(AccountDisabledError):
        await auth_service.authenticate_user(session, "testuser", TEST_PASSWORD)

    assert session.commit_count == 0


async def test_login_returns_token_response() -> None:
    user = make_user()
    session = FakeSession(user)

    response = await auth_service.login(session, "testuser", TEST_PASSWORD)

    assert response.token_type == "bearer"
    assert response.expires_in == settings.access_token_expire_minutes * 60
    assert response.user.id == user.id
    payload = decode_access_token(response.access_token)
    assert payload.sub == str(user.id)


async def test_resolve_user_from_token_returns_user() -> None:
    user = make_user()
    session = FakeSession(user)

    resolved = await auth_service.resolve_user_from_token(session, create_access_token(user.id))

    assert resolved is user


async def test_resolve_user_from_token_rejects_unknown_user() -> None:
    session = FakeSession(None)

    with pytest.raises(InvalidTokenError):
        await auth_service.resolve_user_from_token(session, create_access_token(uuid4()))


async def test_resolve_user_from_token_rejects_disabled_user() -> None:
    user = make_user(is_active=False)
    session = FakeSession(user)

    with pytest.raises(AccountDisabledError):
        await auth_service.resolve_user_from_token(session, create_access_token(user.id))


async def test_resolve_user_from_token_rejects_expired_token() -> None:
    user = make_user()
    session = FakeSession(user)
    token = create_access_token(user.id, expires_delta=timedelta(seconds=-60))

    with pytest.raises(TokenExpiredError):
        await auth_service.resolve_user_from_token(session, token)
