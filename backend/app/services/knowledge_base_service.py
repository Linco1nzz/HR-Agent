"""知识库业务逻辑：查询、创建、编辑、删除与权限校验。

权限规则：

* 任何登录用户都可以创建知识库；
* 编辑 / 删除知识库需要管理员（``is_superuser`` 或管理员角色）；
* 非管理员只能看到公开知识库与自己创建的知识库。

删除知识库时不会删除文档文件与向量块，只把文档的 ``knowledge_base_id``
置空；只有删除文档时才清理文件、文档记录与向量块（见
:mod:`app.services.document_service`）。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import ColumnElement, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestError,
    ForbiddenError,
    KnowledgeBaseNameExistsError,
    KnowledgeBaseNotFoundError,
)
from app.core.logging import get_logger
from app.db.models import Document, KnowledgeBase, User
from app.schemas.knowledge_base import KnowledgeBaseCreate, KnowledgeBaseUpdate

logger = get_logger(__name__)

#: 除 ``is_superuser`` 外，这些角色名也视为管理员
ADMIN_ROLE_NAMES = frozenset({"admin", "administrator", "超级管理员", "管理员"})
_EDIT_DENIED_MESSAGE = "只有管理员可以编辑或删除知识库"
_VIEW_DENIED_MESSAGE = "无权访问该知识库"


# ---------------------------------------------------------------------------
# 权限
# ---------------------------------------------------------------------------
def is_admin(user: User) -> bool:
    """是否为管理员（超级管理员标记或管理员角色）。"""
    if user.is_superuser:
        return True
    return any(getattr(role, "name", "") in ADMIN_ROLE_NAMES for role in (user.roles or []))


def ensure_admin(user: User) -> None:
    """非管理员抛 403。"""
    if not is_admin(user):
        raise ForbiddenError(_EDIT_DENIED_MESSAGE)


def ensure_can_view(record: KnowledgeBase, user: User) -> None:
    """公开知识库、自己创建的知识库或管理员可查看。"""
    if is_admin(user) or record.is_public or record.created_by == user.id:
        return
    raise ForbiddenError(_VIEW_DENIED_MESSAGE)


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
async def list_knowledge_bases(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    user: User,
    keyword: str | None = None,
    category: str | None = None,
    is_public: bool | None = None,
) -> tuple[list[KnowledgeBase], int]:
    """分页查询可见的知识库，按更新时间倒序。"""
    filters: list[ColumnElement[bool]] = [KnowledgeBase.is_active.is_(True)]
    filters.extend(_visibility_filters(user))

    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        filters.append(
            or_(
                KnowledgeBase.name.ilike(pattern),
                KnowledgeBase.description.ilike(pattern),
            )
        )
    if category:
        filters.append(KnowledgeBase.category == category)
    if is_public is not None:
        filters.append(KnowledgeBase.is_public.is_(is_public))

    total = await db.scalar(select(func.count()).select_from(KnowledgeBase).where(*filters)) or 0
    stmt = (
        select(KnowledgeBase)
        .where(*filters)
        .order_by(KnowledgeBase.updated_at.desc(), KnowledgeBase.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.scalars(stmt)).all()
    return list(rows), total


async def get_knowledge_base(
    db: AsyncSession,
    kb_id: UUID,
    *,
    user: User,
    for_write: bool = False,
) -> KnowledgeBase:
    """按 ID 获取知识库；``for_write`` 时校验管理员权限。"""
    record = await db.get(KnowledgeBase, kb_id)
    if record is None or not record.is_active:
        raise KnowledgeBaseNotFoundError(details={"knowledge_base_id": str(kb_id)})
    if for_write:
        ensure_admin(user)
    else:
        ensure_can_view(record, user)
    return record


async def names_by_id(db: AsyncSession, kb_ids: list[UUID]) -> dict[UUID, str]:
    """批量查询知识库名称，供文档列表展示所属知识库。"""
    if not kb_ids:
        return {}
    stmt = select(KnowledgeBase.id, KnowledgeBase.name).where(KnowledgeBase.id.in_(set(kb_ids)))
    rows = (await db.execute(stmt)).all()
    return {row[0]: row[1] for row in rows}


# ---------------------------------------------------------------------------
# 创建 / 更新 / 删除
# ---------------------------------------------------------------------------
async def create_knowledge_base(
    db: AsyncSession,
    payload: KnowledgeBaseCreate,
    *,
    user: User,
) -> KnowledgeBase:
    """创建知识库；任何登录用户都可以创建。"""
    await _ensure_name_available(db, payload.name)
    record = KnowledgeBase(
        **payload.model_dump(),
        document_count=0,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    logger.info(
        "knowledge_base_created",
        knowledge_base_id=str(record.id),
        user_id=str(user.id),
        name=record.name,
    )
    return record


async def update_knowledge_base(
    db: AsyncSession,
    kb_id: UUID,
    payload: KnowledgeBaseUpdate,
    *,
    user: User,
) -> KnowledgeBase:
    """局部更新知识库（仅管理员）；只处理请求中显式传入的字段。"""
    record = await get_knowledge_base(db, kb_id, user=user, for_write=True)
    data = payload.model_dump(exclude_unset=True)

    if "name" in data:
        if data["name"] is None:
            raise BadRequestError("知识库名称不能为 null", details={"field": "name"})
        if data["name"] != record.name:
            await _ensure_name_available(db, data["name"], exclude_id=record.id)

    for field, value in data.items():
        setattr(record, field, value)
    record.updated_by = user.id

    await db.commit()
    await db.refresh(record)
    logger.info(
        "knowledge_base_updated",
        knowledge_base_id=str(record.id),
        user_id=str(user.id),
        fields=sorted(data),
    )
    return record


async def delete_knowledge_base(db: AsyncSession, kb_id: UUID, *, user: User) -> None:
    """删除知识库（仅管理员），文档只解除关联，不删除文件与向量块。"""
    record = await get_knowledge_base(db, kb_id, user=user, for_write=True)
    deleted_id = record.id
    detached_documents = record.document_count

    await db.execute(
        update(Document)
        .where(Document.knowledge_base_id == deleted_id)
        .values(knowledge_base_id=None, updated_by=user.id)
    )
    await db.delete(record)
    await db.commit()
    logger.info(
        "knowledge_base_deleted",
        knowledge_base_id=str(deleted_id),
        user_id=str(user.id),
        detached_documents=detached_documents,
    )


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------
def _visibility_filters(user: User) -> list[ColumnElement[bool]]:
    """非管理员只能看到公开知识库与自己创建的知识库。"""
    if is_admin(user):
        return []
    return [or_(KnowledgeBase.is_public.is_(True), KnowledgeBase.created_by == user.id)]


async def _ensure_name_available(
    db: AsyncSession,
    name: str,
    *,
    exclude_id: UUID | None = None,
) -> None:
    stmt = select(KnowledgeBase.id).where(KnowledgeBase.name == name)
    if exclude_id is not None:
        stmt = stmt.where(KnowledgeBase.id != exclude_id)
    if await db.scalar(stmt.limit(1)) is not None:
        raise KnowledgeBaseNameExistsError(details={"name": name})
