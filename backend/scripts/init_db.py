"""数据库初始化脚本：建表、预置内置角色、创建测试管理员。

主要做三件事：

1. 初始化数据库表（``users`` / ``role`` / ``user_role`` / ``job_description`` /
   ``scoring_criteria`` / ``knowledge_bases`` / ``documents``）。知识库分块向量
   存于 LangChain PGVector 的 ``langchain_pg_embedding`` 表，由 PGVector 首次
   使用时自动创建，不在本脚本建表范围内。
2. 确保存在两个内置角色：普通用户、超级管理员。
3. 确保存在测试管理员 ``testuser``，并把它绑定到超级管理员角色。

脚本是幂等的，可以重复执行，不会重复插入角色、用户或关联记录。

用法（在 ``backend`` 目录下执行）::

    uv run python scripts/init_db.py

测试账号默认密码为 ``test123``（仅用于本地开发/联调，请勿用于生产）。
如果数据库已经由 Alembic 迁移管理，建表也可以改用 ``uv run alembic upgrade head``。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 直接运行 scripts/init_db.py 时，把 backend/ 加入模块搜索路径，
# 这样无需额外设置 PYTHONPATH 也能导入 app 包。
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core.logging import get_logger, setup_logging  # noqa: E402
from app.core.security import get_password_hash  # noqa: E402
from app.db.base import BaseModel  # noqa: E402
from app.db.models import Role, User, UserRoleAssociation  # noqa: E402
from app.db.session import SessionLocal, dispose_engine, engine  # noqa: E402

logger = get_logger(__name__)

# 内置角色：(角色名, 描述)
BUILTIN_ROLES: tuple[tuple[str, str], ...] = (
    ("普通用户", "默认普通用户角色"),
    ("超级管理员", "系统超级管理员角色"),
)

SUPER_ADMIN_ROLE_NAME = "超级管理员"

# 测试管理员账号
TEST_ADMIN_USERNAME = "testuser"
TEST_ADMIN_EMAIL = "testuser@example.com"
TEST_ADMIN_FULL_NAME = "Test Administrator"
TEST_ADMIN_PASSWORD = "test123"


async def create_tables() -> None:
    """按 ORM 元数据创建缺失的表（已存在的表会被跳过）。"""
    async with engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.create_all)
    logger.info("数据库表初始化完成", tables=sorted(BaseModel.metadata.tables))


async def ensure_builtin_roles(db: AsyncSession) -> Role:
    """确保两个内置角色存在，并返回超级管理员角色。"""
    role_names = [name for name, _ in BUILTIN_ROLES]
    result = await db.execute(select(Role).where(Role.name.in_(role_names)))
    roles = {role.name: role for role in result.scalars().all()}

    for name, description in BUILTIN_ROLES:
        role = roles.get(name)
        if role is None:
            role = Role(name=name, description=description, is_builtin=True, is_active=True)
            db.add(role)
            roles[name] = role
            logger.info("创建内置角色", role=name)
            continue
        if not role.is_builtin or not role.is_active:
            role.is_builtin = True
            role.is_active = True
            logger.info("修正内置角色状态", role=name)

    await db.commit()
    return roles[SUPER_ADMIN_ROLE_NAME]


async def ensure_test_admin(db: AsyncSession, admin_role: Role) -> User:
    """确保 testuser 存在、具备管理员标记，并绑定超级管理员角色。"""
    result = await db.execute(select(User).where(User.username == TEST_ADMIN_USERNAME))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            username=TEST_ADMIN_USERNAME,
            email=TEST_ADMIN_EMAIL,
            full_name=TEST_ADMIN_FULL_NAME,
            hashed_password=get_password_hash(TEST_ADMIN_PASSWORD),
            is_superuser=True,
            is_verified=True,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        logger.info("创建测试管理员账号", username=user.username)
    else:
        logger.info("测试管理员账号已存在，跳过创建", username=user.username)
        changed = False
        for field in ("is_superuser", "is_verified", "is_active"):
            if not getattr(user, field):
                setattr(user, field, True)
                changed = True
        if changed:
            await db.commit()
            logger.info("已修正测试账号的管理员状态", username=user.username)

    link = await db.execute(
        select(UserRoleAssociation).where(
            UserRoleAssociation.user_id == user.id,
            UserRoleAssociation.role_id == admin_role.id,
        )
    )
    if link.scalar_one_or_none() is None:
        db.add(UserRoleAssociation(user_id=user.id, role_id=admin_role.id))
        await db.commit()
        logger.info("绑定测试账号与角色", username=user.username, role=admin_role.name)
    else:
        logger.info("测试账号已绑定该角色，跳过", username=user.username, role=admin_role.name)

    return user


async def init_db() -> None:
    """执行完整的初始化流程。"""
    await create_tables()
    async with SessionLocal() as db:
        admin_role = await ensure_builtin_roles(db)
        await ensure_test_admin(db, admin_role)


async def _run() -> None:
    try:
        await init_db()
    finally:
        await dispose_engine()


def main() -> None:
    setup_logging()
    try:
        asyncio.run(_run())
    except Exception:
        logger.exception("数据库初始化失败")
        raise SystemExit(1) from None
    logger.info("数据库初始化完成", test_user=TEST_ADMIN_USERNAME)


if __name__ == "__main__":
    main()
