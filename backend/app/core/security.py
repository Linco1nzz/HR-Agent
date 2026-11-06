"""密码哈希与校验工具（Argon2id）。

使用 ``argon2-cffi`` 的 :class:`~argon2.PasswordHasher`，默认算法为 Argon2id
（内存困难型 KDF）。参数通过 ``settings.argon2_*`` 配置，默认值为
32 MiB 内存 / 2 次迭代 / 2 并行度，低于 argon2-cffi 的默认值；
与 bcrypt 不同，Argon2 没有 72 字节的密码长度限制。
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import settings

_password_hasher = PasswordHasher(
    time_cost=settings.argon2_time_cost,
    memory_cost=settings.argon2_memory_cost,
    parallelism=settings.argon2_parallelism,
)


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
