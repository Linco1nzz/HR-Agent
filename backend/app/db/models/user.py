"""用户、角色与用户角色关联表。

本次只落地这三张表及其多对多关系：

* ``users``：用户账号与个人资料
* ``role``：系统角色
* ``user_role``：用户与角色的关联表（多对多中间表）

按要求暂不建立数据库外键约束，关联数据的完整性由业务层保证；
用户/角色表稳定后再统一补 ``ForeignKey`` 及对应迁移。

``User.roles`` / ``Role.users`` 使用显式 join 条件关联中间表，
因此在没有外键的情况下也能正常加载和写入。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint, Uuid, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel

if TYPE_CHECKING:
    from app.db.models.document import Document


class User(BaseModel):
    """用户账号。"""

    __tablename__ = "users"

    # --- 基本信息 ---
    username: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False, comment="用户名"
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False, comment="邮箱地址"
    )
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="用户全名")
    hashed_password: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="加密后的密码"
    )

    # --- 个人资料 ---
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="手机号")
    department: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="所属部门")
    position: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="职位")
    employee_id: Mapped[str | None] = mapped_column(
        String(50), unique=True, nullable=True, comment="员工编号"
    )

    # --- 账号状态 ---
    is_superuser: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=false(),
        nullable=False,
        comment="是否为超级管理员",
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=false(),
        nullable=False,
        comment="是否已验证",
    )

    # --- 附加信息 ---
    bio: Mapped[str | None] = mapped_column(Text, nullable=True, comment="个人简介")
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="头像地址")
    last_login: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最后登录时间"
    )

    # --- 关系（无外键，显式指定 join 条件）---
    roles: Mapped[list[Role]] = relationship(
        "Role",
        secondary="user_role",
        primaryjoin="User.id == UserRoleAssociation.user_id",
        secondaryjoin="Role.id == UserRoleAssociation.role_id",
        back_populates="users",
    )
    #: 该用户上传的知识库文档；无外键，显式指定 join 条件
    documents: Mapped[list[Document]] = relationship(
        "Document",
        primaryjoin="User.id == foreign(Document.user_id)",
        back_populates="uploaded_by",
        lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<User(username={self.username!r}, email={self.email!r})>"


class Role(BaseModel):
    """系统角色。"""

    __tablename__ = "role"

    name: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False, comment="角色名称"
    )
    description: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="角色描述")
    is_builtin: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=false(),
        nullable=False,
        comment="是否为系统内置角色",
    )

    users: Mapped[list[User]] = relationship(
        "User",
        secondary="user_role",
        primaryjoin="Role.id == UserRoleAssociation.role_id",
        secondaryjoin="User.id == UserRoleAssociation.user_id",
        back_populates="roles",
    )


class UserRoleAssociation(BaseModel):
    """用户与角色的多对多关联表（无外键，业务层保证一致性）。"""

    __tablename__ = "user_role"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, index=True, comment="用户 ID"
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, index=True, comment="角色 ID"
    )

    __table_args__ = (UniqueConstraint("user_id", "role_id"),)
