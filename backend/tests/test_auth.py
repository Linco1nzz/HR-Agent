"""登录、JWT 鉴权与当前用户接口测试。

默认运行的是单元测试：用内存中的假会话替换 ``get_db``，不依赖数据库。
带 ``integration`` 标记的用例会连接真实 PostgreSQL，创建临时账号后验证
完整链路（需先执行 ``uv run python scripts/init_db.py`` 或已完成建表）：

    uv run pytest --run-integration
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.exceptions import InvalidTokenError, TokenExpiredError
from app.core.security import (
    create_access_token,
    decode_access_token,
    get_password_hash,
)
from app.db.models import Role
from app.db.session import get_db
from app.main import app
from tests.fakes import TEST_PASSWORD, FakeSession, make_user

API = settings.api_v1_prefix


@pytest.fixture()
def auth_client() -> Iterator[tuple[TestClient, FakeSession]]:
    """带 ``get_db`` 覆盖的测试客户端；可在用例中替换 ``session.user``。"""
    session = FakeSession()

    async def _override_get_db() -> AsyncIterator[FakeSession]:
        yield session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as client:
            yield client, session
    finally:
        app.dependency_overrides.clear()


def login(client: TestClient, username: str = "testuser", password: str = TEST_PASSWORD) -> Any:
    return client.post(
        f"{API}/auth/login",
        json={"username": username, "password": password},
    )


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 登录接口
# ---------------------------------------------------------------------------
def test_login_returns_token_and_user(auth_client: tuple[TestClient, FakeSession]) -> None:
    client, session = auth_client
    user = make_user()
    user.roles.append(Role(name="超级管理员"))
    session.user = user

    response = login(client)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.access_token_expire_minutes * 60

    payload = decode_access_token(body["access_token"])
    assert payload.sub == str(user.id)
    assert payload.type == "access"
    assert payload.exp > payload.iat

    user_body = body["user"]
    assert user_body["id"] == str(user.id)
    assert user_body["username"] == "testuser"
    assert user_body["email"] == "testuser@example.com"
    assert user_body["roles"] == ["超级管理员"]
    assert "hashed_password" not in user_body

    # 登录成功会记录最后登录时间
    assert session.commit_count == 1
    assert user.last_login is not None


def test_login_with_wrong_password(auth_client: tuple[TestClient, FakeSession]) -> None:
    client, session = auth_client
    session.user = make_user()

    response = login(client, password="wrong-password")

    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "INVALID_CREDENTIALS"
    assert body["message"] == "用户名或密码错误"
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert session.commit_count == 0


def test_login_with_unknown_account(auth_client: tuple[TestClient, FakeSession]) -> None:
    client, session = auth_client
    session.user = None

    response = login(client, username="nobody")

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"
    assert session.commit_count == 0


def test_login_with_disabled_account(auth_client: tuple[TestClient, FakeSession]) -> None:
    client, session = auth_client
    session.user = make_user(is_active=False)

    response = login(client)

    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "ACCOUNT_DISABLED"
    assert body["message"] == "账号已被停用，请联系管理员"
    assert session.commit_count == 0


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"username": "testuser"},
        {"password": TEST_PASSWORD},
        {"username": "", "password": TEST_PASSWORD},
        {"username": "   ", "password": TEST_PASSWORD},
        {"username": "testuser", "password": ""},
    ],
    ids=["empty", "no-password", "no-username", "blank-username", "spaces", "empty-password"],
)
def test_login_validation_errors(
    auth_client: tuple[TestClient, FakeSession],
    payload: dict[str, str],
) -> None:
    client, _ = auth_client

    response = client.post(f"{API}/auth/login", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["details"]["errors"]


# ---------------------------------------------------------------------------
# 当前用户接口
# ---------------------------------------------------------------------------
def test_me_with_valid_token(auth_client: tuple[TestClient, FakeSession]) -> None:
    client, session = auth_client
    user = make_user()
    session.user = user

    response = client.get(f"{API}/auth/me", headers=bearer(create_access_token(user.id)))

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(user.id)
    assert body["username"] == user.username
    assert "hashed_password" not in body


def test_me_without_token(auth_client: tuple[TestClient, FakeSession]) -> None:
    client, _ = auth_client

    response = client.get(f"{API}/auth/me")

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_TOKEN"
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_me_with_malformed_token(auth_client: tuple[TestClient, FakeSession]) -> None:
    client, _ = auth_client

    response = client.get(f"{API}/auth/me", headers=bearer("not-a-jwt"))

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_TOKEN"


def test_me_with_expired_token(auth_client: tuple[TestClient, FakeSession]) -> None:
    client, session = auth_client
    user = make_user()
    session.user = user
    expired = create_access_token(user.id, expires_delta=timedelta(seconds=-60))

    response = client.get(f"{API}/auth/me", headers=bearer(expired))

    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_EXPIRED"


def test_me_with_deleted_user(auth_client: tuple[TestClient, FakeSession]) -> None:
    client, session = auth_client
    token = create_access_token(uuid4())
    session.user = None

    response = client.get(f"{API}/auth/me", headers=bearer(token))

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_TOKEN"


def test_me_with_disabled_account(auth_client: tuple[TestClient, FakeSession]) -> None:
    client, session = auth_client
    user = make_user(is_active=False)
    session.user = user

    response = client.get(f"{API}/auth/me", headers=bearer(create_access_token(user.id)))

    assert response.status_code == 403
    assert response.json()["code"] == "ACCOUNT_DISABLED"


# ---------------------------------------------------------------------------
# 退出登录
# ---------------------------------------------------------------------------
def test_logout(auth_client: tuple[TestClient, FakeSession]) -> None:
    client, session = auth_client
    user = make_user()
    session.user = user

    response = client.post(f"{API}/auth/logout", headers=bearer(create_access_token(user.id)))

    assert response.status_code == 200
    assert response.json()["message"] == "已退出登录"


# ---------------------------------------------------------------------------
# JWT 签发 / 校验
# ---------------------------------------------------------------------------
def test_access_token_claims() -> None:
    user_id = uuid4()

    token = create_access_token(user_id)
    payload = decode_access_token(token)
    raw = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])

    assert payload.sub == str(user_id)
    assert payload.jti
    assert raw["type"] == "access"
    expected = timedelta(minutes=settings.access_token_expire_minutes)
    assert abs((payload.exp - payload.iat) - expected) <= timedelta(seconds=1)


def test_expired_token_is_rejected() -> None:
    token = create_access_token(uuid4(), expires_delta=timedelta(seconds=-60))

    with pytest.raises(TokenExpiredError):
        decode_access_token(token)


def test_token_signed_with_other_secret_is_rejected() -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "jti": uuid4().hex,
            "type": "access",
        },
        "another-secret-value-used-only-in-tests",
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_token_with_invalid_subject_is_rejected() -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "not-a-uuid",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "jti": uuid4().hex,
            "type": "access",
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_token_with_wrong_type_is_rejected() -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "jti": uuid4().hex,
            "type": "refresh",
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_token_missing_required_claims_is_rejected() -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            # 缺少 jti
            "type": "access",
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


# ---------------------------------------------------------------------------
# OpenAPI
# ---------------------------------------------------------------------------
def test_openapi_documents_auth_endpoints(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert f"{API}/auth/login" in paths
    assert f"{API}/auth/me" in paths
    assert f"{API}/auth/logout" in paths
    assert "securitySchemes" in client.get("/openapi.json").json()["components"]


# ---------------------------------------------------------------------------
# 集成测试：真实 PostgreSQL
# ---------------------------------------------------------------------------
def _sync_database_url() -> str:
    """把应用的 asyncpg / psycopg URL 转成 psycopg 同步连接串。"""
    url = make_url(settings.database_url).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


@pytest.mark.integration
def test_login_flow_against_real_database(client: TestClient) -> None:
    """真实数据库链路：用户名 / 邮箱登录、令牌鉴权、错误密码、停用账号。"""
    user_id = uuid4()
    username = f"login_test_{user_id.hex[:8]}"
    email = f"{username}@example.com"
    password = "Login-test-123"
    db_url = _sync_database_url()

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users
                    (id, username, email, full_name, hashed_password,
                     is_verified, is_superuser, is_active)
                VALUES (%s, %s, %s, %s, %s, true, false, true)
                """,
                (user_id, username, email, "Login Test", get_password_hash(password)),
            )
        conn.commit()

    try:
        response = login(client, username=username, password=password)
        assert response.status_code == 200, response.text
        body = response.json()
        token = body["access_token"]
        assert body["user"]["id"] == str(user_id)
        assert body["user"]["username"] == username
        assert "hashed_password" not in body["user"]

        # 登录会更新 last_login
        with psycopg.connect(db_url) as conn:
            last_login = conn.execute(
                "SELECT last_login FROM users WHERE id = %s", (user_id,)
            ).fetchone()
        assert last_login is not None and last_login[0] is not None

        # 邮箱登录大小写不敏感
        response = login(client, username=email.upper(), password=password)
        assert response.status_code == 200, response.text

        # 令牌可用于访问受保护接口
        response = client.get(f"{API}/auth/me", headers=bearer(token))
        assert response.status_code == 200, response.text
        assert response.json()["id"] == str(user_id)

        # 密码错误
        response = login(client, username=username, password="wrong-password")
        assert response.status_code == 401
        assert response.json()["code"] == "INVALID_CREDENTIALS"

        # 停用后既不能登录，已签发令牌也立即失效
        with psycopg.connect(db_url) as conn:
            conn.execute("UPDATE users SET is_active = false WHERE id = %s", (user_id,))
            conn.commit()

        response = login(client, username=username, password=password)
        assert response.status_code == 403
        assert response.json()["code"] == "ACCOUNT_DISABLED"

        response = client.get(f"{API}/auth/me", headers=bearer(token))
        assert response.status_code == 403
        assert response.json()["code"] == "ACCOUNT_DISABLED"
    finally:
        with psycopg.connect(db_url) as conn:
            conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
            conn.commit()


def test_token_payload_subject_is_uuid_instance() -> None:
    """``decode_access_token`` 返回的 ``sub`` 可安全转成 UUID。"""
    user_id = uuid4()

    payload = decode_access_token(create_access_token(user_id))

    assert isinstance(UUID(payload.sub), UUID)
    assert str(user_id) == payload.sub
