"""知识库权限规则测试：管理员判定与可见性校验（不依赖数据库）。"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.core.exceptions import ForbiddenError
from app.db.models import KnowledgeBase, Role
from app.services import knowledge_base_service
from tests.fakes import make_user


def make_knowledge_base(**overrides: Any) -> KnowledgeBase:
    data: dict[str, Any] = {
        "name": "员工手册",
        "description": "公司制度",
        "is_public": False,
        "is_searchable": True,
        "document_count": 0,
        "is_active": True,
    }
    data.update(overrides)
    return KnowledgeBase(**data)


def make_role(name: str) -> Role:
    return Role(name=name, is_builtin=False, is_active=True)


def test_superuser_is_admin() -> None:
    assert knowledge_base_service.is_admin(make_user(is_superuser=True))


def test_admin_role_is_admin() -> None:
    user = make_user()
    user.roles = [make_role("超级管理员")]

    assert knowledge_base_service.is_admin(user)


def test_regular_user_is_not_admin() -> None:
    assert not knowledge_base_service.is_admin(make_user())


def test_ensure_admin_rejects_regular_user() -> None:
    with pytest.raises(ForbiddenError):
        knowledge_base_service.ensure_admin(make_user())


def test_ensure_admin_accepts_superuser() -> None:
    knowledge_base_service.ensure_admin(make_user(is_superuser=True))


def test_public_knowledge_base_visible_to_everyone() -> None:
    record = make_knowledge_base(is_public=True, created_by=uuid4())

    knowledge_base_service.ensure_can_view(record, make_user())


def test_owner_can_view_private_knowledge_base() -> None:
    user = make_user()
    record = make_knowledge_base(created_by=user.id)

    knowledge_base_service.ensure_can_view(record, user)


def test_private_knowledge_base_hidden_from_others() -> None:
    record = make_knowledge_base(created_by=uuid4())

    with pytest.raises(ForbiddenError):
        knowledge_base_service.ensure_can_view(record, make_user())


def test_admin_can_view_any_knowledge_base() -> None:
    record = make_knowledge_base(created_by=uuid4())

    knowledge_base_service.ensure_can_view(record, make_user(is_superuser=True))
