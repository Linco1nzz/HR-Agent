"""问答会话业务逻辑：会话 / 消息 CRUD、归属校验与问答落库辅助。

权限规则：会话仅创建者本人可见、可操作；访问他人会话一律按「不存在」处理
（抛 :class:`ConversationNotFoundError`），避免泄露会话是否存在。

会话绑定的知识库必须存在且对当前用户可见，复用
:mod:`app.services.knowledge_base_service` 的可见性校验。
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestError, ConversationNotFoundError, MessageNotFoundError
from app.core.logging import get_logger
from app.db.models import Conversation, Message, User
from app.schemas.conversation import (
    ConversationCreate,
    ConversationUpdate,
    MessageFeedback,
)
from app.services import knowledge_base_service

logger = get_logger(__name__)

#: 未显式指定标题时的默认值；首条用户消息会据此自动生成标题
DEFAULT_TITLE = "新会话"
#: 自动标题的最大字符数
AUTO_TITLE_MAX_CHARS = 30


# ---------------------------------------------------------------------------
# 会话 CRUD
# ---------------------------------------------------------------------------
async def create_conversation(
    db: AsyncSession,
    payload: ConversationCreate,
    *,
    user: User,
) -> Conversation:
    """创建会话；绑定的知识库需存在且当前用户可见。"""
    kb_ids = await validate_knowledge_base_ids(db, payload.knowledge_base_ids, user=user)
    record = Conversation(
        title=payload.title or DEFAULT_TITLE,
        kind=payload.kind.value,
        description=payload.description,
        knowledge_base_ids=[str(kb_id) for kb_id in kb_ids],
        total_messages=0,
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    logger.info(
        "conversation_created",
        conversation_id=str(record.id),
        user_id=str(user.id),
        knowledge_base_ids=[str(kb_id) for kb_id in kb_ids],
    )
    return record


async def list_conversations(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    user: User,
    kind: str | None = None,
) -> tuple[list[Conversation], int]:
    """分页查询当前用户的会话，按更新时间倒序；可按 kind 过滤。"""
    filters = [Conversation.user_id == user.id, Conversation.is_active.is_(True)]
    if kind is not None:
        filters.append(Conversation.kind == kind)
    total = await db.scalar(select(func.count()).select_from(Conversation).where(*filters)) or 0
    stmt = (
        select(Conversation)
        .where(*filters)
        .order_by(Conversation.updated_at.desc(), Conversation.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.scalars(stmt)).all()
    return list(rows), total


async def get_conversation(
    db: AsyncSession,
    conversation_id: UUID,
    *,
    user: User,
) -> Conversation:
    """按 ID 获取当前用户的会话；不存在或不属于该用户时抛 404。"""
    record = await db.get(Conversation, conversation_id)
    if record is None or not record.is_active or record.user_id != user.id:
        raise ConversationNotFoundError(details={"conversation_id": str(conversation_id)})
    return record


async def update_conversation(
    db: AsyncSession,
    conversation_id: UUID,
    payload: ConversationUpdate,
    *,
    user: User,
) -> Conversation:
    """局部更新会话；只处理请求中显式传入的字段。"""
    record = await get_conversation(db, conversation_id, user=user)
    data = payload.model_dump(exclude_unset=True)

    if "title" in data and data["title"] is None:
        raise BadRequestError("会话标题不能为 null", details={"field": "title"})
    if "knowledge_base_ids" in data:
        kb_ids = await validate_knowledge_base_ids(db, data["knowledge_base_ids"] or [], user=user)
        data["knowledge_base_ids"] = [str(kb_id) for kb_id in kb_ids]

    for field, value in data.items():
        setattr(record, field, value)
    record.updated_by = user.id

    await db.commit()
    await db.refresh(record)
    logger.info(
        "conversation_updated",
        conversation_id=str(record.id),
        user_id=str(user.id),
        fields=sorted(data),
    )
    return record


async def delete_conversation(db: AsyncSession, conversation_id: UUID, *, user: User) -> None:
    """删除会话及其全部消息（ORM cascade）。"""
    await get_conversation(db, conversation_id, user=user)
    stmt = (
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.id == conversation_id)
    )
    record = (await db.scalars(stmt)).one()
    message_count = len(record.messages)
    await db.delete(record)
    await db.commit()
    logger.info(
        "conversation_deleted",
        conversation_id=str(conversation_id),
        user_id=str(user.id),
        deleted_messages=message_count,
    )


# ---------------------------------------------------------------------------
# 消息
# ---------------------------------------------------------------------------
async def list_messages(
    db: AsyncSession,
    conversation_id: UUID,
    *,
    page: int,
    page_size: int,
    user: User,
) -> tuple[list[Message], int]:
    """分页查询会话消息，按创建时间升序。"""
    await get_conversation(db, conversation_id, user=user)
    filters = [Message.conversation_id == conversation_id]
    total = await db.scalar(select(func.count()).select_from(Message).where(*filters)) or 0
    stmt = (
        select(Message)
        .where(*filters)
        .order_by(Message.created_at.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.scalars(stmt)).all()
    return list(rows), total


async def get_message(
    db: AsyncSession,
    conversation_id: UUID,
    message_id: UUID,
    *,
    user: User,
) -> Message:
    """获取会话内的一条消息；会话归属与消息归属都需校验。"""
    await get_conversation(db, conversation_id, user=user)
    record = await db.get(Message, message_id)
    if record is None or record.conversation_id != conversation_id:
        raise MessageNotFoundError(
            details={"conversation_id": str(conversation_id), "message_id": str(message_id)}
        )
    return record


async def update_message_feedback(
    db: AsyncSession,
    conversation_id: UUID,
    message_id: UUID,
    payload: MessageFeedback,
    *,
    user: User,
) -> Message:
    """记录用户对消息的评分与反馈。"""
    record = await get_message(db, conversation_id, message_id, user=user)
    record.rating = payload.rating
    record.feedback = payload.feedback
    record.updated_by = user.id
    await db.commit()
    await db.refresh(record)
    logger.info(
        "message_feedback_saved",
        conversation_id=str(conversation_id),
        message_id=str(message_id),
        rating=payload.rating,
    )
    return record


# ---------------------------------------------------------------------------
# 问答落库辅助（供 qa_service 在独立会话中调用）
# ---------------------------------------------------------------------------
async def update_total_messages(db: AsyncSession, conversation_id: UUID) -> int:
    """重算会话消息总数并刷新更新时间；调用方负责提交。"""
    await db.flush()
    total = (
        await db.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation_id)
        )
        or 0
    )
    record = await db.get(Conversation, conversation_id)
    if record is not None:
        record.total_messages = total
        record.updated_at = datetime.now(UTC)
    return total


def auto_title(conversation: Conversation, first_user_content: str) -> None:
    """标题仍为默认值时，用首条用户消息截断生成标题。"""
    if conversation.title != DEFAULT_TITLE:
        return
    conversation.title = first_user_content.strip()[:AUTO_TITLE_MAX_CHARS] or DEFAULT_TITLE


async def validate_knowledge_base_ids(
    db: AsyncSession,
    kb_ids: list[UUID],
    *,
    user: User,
) -> list[UUID]:
    """校验知识库存在且当前用户可见；去重并保持原顺序。"""
    seen: set[UUID] = set()
    validated: list[UUID] = []
    for kb_id in kb_ids:
        if kb_id in seen:
            continue
        seen.add(kb_id)
        await knowledge_base_service.get_knowledge_base(db, kb_id, user=user)
        validated.append(kb_id)
    return validated
