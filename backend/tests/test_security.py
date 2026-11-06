"""密码哈希与校验测试（Argon2id）。"""

from __future__ import annotations

from app.core.config import settings
from app.core.security import get_password_hash, verify_password


def test_hash_and_verify_password() -> None:
    hashed = get_password_hash("test123")

    assert hashed != "test123"
    assert hashed.startswith("$argon2id$")
    assert verify_password("test123", hashed)
    assert not verify_password("wrong-password", hashed)


def test_argon2_parameters_from_settings() -> None:
    """哈希参数应取自 settings，便于按环境调整。"""
    hashed = get_password_hash("test123")
    expected = (
        f"m={settings.argon2_memory_cost},"
        f"t={settings.argon2_time_cost},"
        f"p={settings.argon2_parallelism}"
    )
    assert expected in hashed


def test_long_password_is_not_truncated() -> None:
    """Argon2 没有 bcrypt 的 72 字节限制，长密码必须完整参与哈希。"""
    password = "a" * 100
    hashed = get_password_hash(password)

    assert verify_password(password, hashed)
    assert not verify_password("a" * 72, hashed)


def test_invalid_hash_returns_false() -> None:
    assert not verify_password("test123", "not-a-valid-hash")
