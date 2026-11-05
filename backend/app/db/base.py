"""SQLAlchemy 声明式基类：公共字段与自动表名。

所有 ORM 模型继承 :class:`BaseModel` 即可自动获得：

* 主键 ``id``：UUID，客户端默认 ``uuid4()``，数据库默认 ``gen_random_uuid()``
* 审计字段 ``created_at`` / ``updated_at`` / ``created_by`` / ``updated_by``
* 启用标记 ``is_active``
* 表名：类名自动转 snake_case（``EmployeeProfile`` → ``employee_profile``），
  模型内显式声明 ``__tablename__`` 时以显式值为准。

用法::

    class Employee(BaseModel):
        name: Mapped[str] = mapped_column(String(64))
        # 自动使用表名 employee

    class Department(BaseModel):
        __tablename__ = "hr_department"  # 显式指定，不再自动生成
        name: Mapped[str] = mapped_column(String(64))

``created_by`` / ``updated_by`` 存用户 ID（UUID），暂不建外键：用户表落地后
再按需添加 ``ForeignKey``，并由业务层在写入时赋值。
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, MetaData, Uuid, func, text, true
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 约束/索引命名规范：让 Alembic 自动生成的迁移名称稳定、可回滚
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# CamelCase 边界：aB / ABc 处插入下划线，连续大写（如 HR）视为一个词
_CAMEL_CASE_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def camel_to_snake(name: str) -> str:
    """把 CamelCase 类名转成 snake_case 表名。"""
    return _CAMEL_CASE_BOUNDARY.sub("_", name).lower()


class BaseModel(DeclarativeBase):
    """所有 ORM 模型的基类（抽象类，本身不建表）。

    子类若不声明 ``__tablename__``，会自动按类名生成；
    抽象子类（``__abstract__ = True``）、显式 ``__table__`` 以及继承自
    已映射父类的子类（单表/联表继承）不会被自动命名覆盖。
    """

    __abstract__ = True

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    # --- 主键 ---
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
        comment="主键",
    )

    # --- 审计字段 ---
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        comment="创建人 ID",
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        comment="更新人 ID",
    )

    # --- 启用标记 ---
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
        comment="是否启用",
    )

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """在 SQLAlchemy 完成映射前，为子类补全 ``__tablename__``。

        ``DeclarativeBase`` 通过 ``__init_subclass__`` 建立映射，因此必须在
        ``super().__init_subclass__()`` 之前写入表名，映射时才能读到。
        """
        if (
            "__tablename__" not in cls.__dict__  # 未显式指定表名
            and "__table__" not in cls.__dict__  # 未使用 __table__ 手动建表
            and not cls.__dict__.get("__abstract__", False)  # 跳过抽象类
            # 继承自已映射父类时保持单表/联表继承语义，不另生表名
            and not any("__table__" in base.__dict__ for base in cls.__bases__)
        ):
            cls.__tablename__ = camel_to_snake(cls.__name__)
        super().__init_subclass__(**kwargs)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} id={self.id!r}>"
