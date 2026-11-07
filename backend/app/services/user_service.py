"""用户数据访问服务。

集中封装用户查询，供认证等业务逻辑复用。所有查询统一预加载角色，
避免在异步上下文中触发懒加载（``MissingGreenlet``）。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import User


async def get_user_by_identifier(db: AsyncSession, identifier: str) -> User | None:
    """按用户名或邮箱查找用户（邮箱大小写不敏感）。"""
    stmt = (
        select(User)
        .options(selectinload(User.roles))
        .where(
            or_(
                User.username == identifier,
                func.lower(User.email) == identifier.lower(),
            )
        )
        .limit(1)
    )
    return await db.scalar(stmt)


async def get_user_by_id(db: AsyncSession, user_id: UUID) -> User | None:
    """按 ID 查找用户，并预加载角色。"""
    stmt = select(User).options(selectinload(User.roles)).where(User.id == user_id).limit(1)
    return await db.scalar(stmt)
