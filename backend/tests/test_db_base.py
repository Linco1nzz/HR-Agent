"""ORM 基类测试：公共字段与自动表名（纯元数据检查，不连数据库）。"""

from __future__ import annotations

from typing import cast

from sqlalchemy import String, Table
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import BaseModel, camel_to_snake


class AutoNamedSample(BaseModel):
    name: Mapped[str] = mapped_column(String(20))


class ExplicitNamedSample(BaseModel):
    __tablename__ = "explicit_named_sample"

    name: Mapped[str] = mapped_column(String(20))


class AbstractSample(BaseModel):
    __abstract__ = True


class ConcreteSample(AbstractSample):
    name: Mapped[str] = mapped_column(String(20))


class MappedParent(BaseModel):
    kind: Mapped[str] = mapped_column(String(10))


class MappedChild(MappedParent):
    pass


def test_camel_to_snake() -> None:
    assert camel_to_snake("EmployeeProfile") == "employee_profile"
    assert camel_to_snake("HRDepartment") == "hr_department"
    assert camel_to_snake("Employee") == "employee"


def test_tablename_auto_generated() -> None:
    assert AutoNamedSample.__tablename__ == "auto_named_sample"
    table = cast(Table, AutoNamedSample.__table__)
    assert table.name == "auto_named_sample"


def test_explicit_tablename_wins() -> None:
    assert ExplicitNamedSample.__tablename__ == "explicit_named_sample"
    table = cast(Table, ExplicitNamedSample.__table__)
    assert table.name == "explicit_named_sample"


def test_abstract_class_not_mapped_but_subclass_is() -> None:
    assert "abstract_sample" not in BaseModel.metadata.tables
    assert ConcreteSample.__tablename__ == "concrete_sample"


def test_mapped_subclass_keeps_inheritance() -> None:
    """继承已映射父类的子类按单表继承处理，不会被自动命名成新表。"""
    assert MappedChild.__table__ is MappedParent.__table__
    assert MappedChild.__tablename__ == "mapped_parent"


def test_common_columns() -> None:
    table = cast(Table, AutoNamedSample.__table__)

    assert [column.name for column in table.primary_key] == ["id"]
    assert table.c.id.default is not None
    assert table.c.id.server_default is not None

    assert table.c.created_at.nullable is False
    assert table.c.created_at.server_default is not None
    assert table.c.updated_at.nullable is False
    assert table.c.updated_at.onupdate is not None

    assert table.c.created_by.nullable is True
    assert table.c.updated_by.nullable is True

    assert table.c.is_active.nullable is False
    assert table.c.is_active.default is not None


def test_primary_key_naming_convention() -> None:
    table = cast(Table, AutoNamedSample.__table__)
    assert table.primary_key.name == "pk_auto_named_sample"
