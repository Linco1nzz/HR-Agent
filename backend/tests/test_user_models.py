"""用户 / 角色 / 用户角色关联表测试（纯元数据检查，不连数据库）。"""

from __future__ import annotations

from typing import cast

from sqlalchemy import Table

from app.db.base import BaseModel
from app.db.models.user import Role, User, UserRoleAssociation


def test_three_tables_registered() -> None:
    assert {"users", "role", "user_role"} <= set(BaseModel.metadata.tables)
    assert User.__tablename__ == "users"
    assert Role.__tablename__ == "role"
    assert UserRoleAssociation.__tablename__ == "user_role"


def test_user_columns() -> None:
    table = cast(Table, User.__table__)
    expected = {
        "username",
        "email",
        "full_name",
        "hashed_password",
        "phone",
        "department",
        "position",
        "employee_id",
        "is_superuser",
        "is_verified",
        "bio",
        "avatar_url",
        "last_login",
    }
    assert expected <= set(table.c.keys())
    assert table.c.username.nullable is False
    assert table.c.email.nullable is False
    assert table.c.hashed_password.nullable is False
    assert table.c.employee_id.nullable is True


def test_unique_indexes() -> None:
    table = cast(Table, User.__table__)
    unique_columns = {
        tuple(column.name for column in index.columns) for index in table.indexes if index.unique
    }
    assert ("username",) in unique_columns
    assert ("email",) in unique_columns

    role_table = cast(Table, Role.__table__)
    assert any(
        index.unique and [c.name for c in index.columns] == ["name"] for index in role_table.indexes
    )


def test_no_foreign_keys() -> None:
    """本次不建外键，关联表只保留普通 UUID 列。"""
    for model in (User, Role, UserRoleAssociation):
        table = cast(Table, model.__table__)
        assert not table.foreign_keys


def test_user_role_association_constraints() -> None:
    table = cast(Table, UserRoleAssociation.__table__)
    column_names = set(table.c.keys())
    assert {"user_id", "role_id"} <= column_names

    constraint_names = {constraint.name for constraint in table.constraints}
    assert "pk_user_role" in constraint_names
    assert "uq_user_role_user_id_role_id" in constraint_names

    indexed_columns = {column.name for index in table.indexes for column in index.columns}
    assert {"user_id", "role_id"} <= indexed_columns


def test_relationships_work_without_foreign_keys() -> None:
    user = User(username="alice", email="alice@example.com", hashed_password="x")
    role = Role(name="admin")

    user.roles.append(role)

    assert role in user.roles
    assert user in role.users
