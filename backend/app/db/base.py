"""SQLAlchemy 声明式基类。"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有 ORM 模型的基类（供 Alembic 自动生成迁移使用）。"""
