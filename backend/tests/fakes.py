"""测试共用假对象：不依赖数据库的会话替身与用户工厂。"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.core.security import get_password_hash
from app.db.models import User

TEST_PASSWORD = "test123"
#: 固定密码哈希只计算一次，避免每个用例重复做 Argon2
TEST_PASSWORD_HASH = get_password_hash(TEST_PASSWORD)


class FakeSession:
    """只实现登录 / 鉴权路径用到的 :class:`AsyncSession` 子集。"""

    def __init__(self, user: User | None = None) -> None:
        self.user = user
        self.commit_count = 0

    async def scalar(self, statement: Any) -> User | None:  # noqa: ARG002 - 不解析查询语句
        return self.user

    async def commit(self) -> None:
        self.commit_count += 1


def make_user(**overrides: Any) -> User:
    """构造一个未绑定会话的用户对象，供假会话返回。"""
    data: dict[str, Any] = {
        "id": uuid4(),
        "username": "testuser",
        "email": "testuser@example.com",
        "full_name": "Test Administrator",
        "hashed_password": TEST_PASSWORD_HASH,
        "is_superuser": False,
        "is_verified": True,
        "is_active": True,
    }
    data.update(overrides)
    return User(**data)
