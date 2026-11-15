"""知识库问答的会话与消息模型。

按项目约定不建数据库外键，``user_id`` / ``conversation_id`` / ``parent_message_id``
的关联完整性由业务层保证；删除会话时由 ORM ``cascade="all, delete-orphan"``
一并删除其消息。会话绑定的知识库以 UUID 字符串列表存在 ``knowledge_base_ids``
（JSONB）中，知识库被删除后由检索层自动忽略失效 ID。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Float, Index, Integer, String, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel

if TYPE_CHECKING:
    from app.db.models.user import User


class Conversation(BaseModel):
    """用户与 HR 助手的一次问答会话。"""

    __tablename__ = "conversations"

    # --- 基本信息 ---
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="新会话",
        server_default="新会话",
        comment="会话标题",
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="会话描述")
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        server_default="active",
        comment="会话状态：active / archived",
    )
    meta_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="会话扩展元数据",
    )
    total_messages: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="消息总数",
    )
    knowledge_base_ids: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
        comment="绑定的知识库 ID 列表（UUID 字符串）",
    )

    # --- 关系 ---
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
        comment="所属用户 ID",
    )

    user: Mapped[User] = relationship(
        "User",
        primaryjoin="foreign(Conversation.user_id) == User.id",
        back_populates="conversations",
        lazy="raise",
    )
    messages: Mapped[list[Message]] = relationship(
        "Message",
        primaryjoin="Conversation.id == foreign(Message.conversation_id)",
        back_populates="conversation",
        cascade="all, delete-orphan",
        # 无数据库外键：删除前需显式 selectinload 消息；passive_deletes 避免
        # flush 时为处理反向关系而触发 lazy="raise" 的隐式加载
        passive_deletes=True,
        order_by="Message.created_at",
        lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<Conversation(title={self.title!r}, status={self.status!r})>"


class Message(BaseModel):
    """会话中的一条消息（用户提问 / 助手回答 / 系统提示）。"""

    __tablename__ = "messages"

    # --- 内容 ---
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="消息文本")
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="消息角色：user / assistant / system",
    )
    model_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="生成该消息的模型名称",
    )
    tokens_used: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="生成消耗的 token 数",
    )
    response_time: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="回答耗时（秒）",
    )
    context: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="回答上下文（路由、改写、关键词、引用来源等）",
    )
    meta_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="消息扩展元数据（如流式中断时的错误信息）",
    )

    # --- 用户反馈 ---
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="用户评分 1~5")
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True, comment="用户反馈文本")

    # --- 关系 ---
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
        comment="所属会话 ID",
    )
    parent_message_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        comment="父消息 ID（自引用，串起问答链路）",
    )

    conversation: Mapped[Conversation] = relationship(
        "Conversation",
        primaryjoin="foreign(Message.conversation_id) == Conversation.id",
        back_populates="messages",
        # 无数据库外键：级联删除 flush 时不隐式加载父对象（配合 lazy="raise"）
        passive_deletes=True,
        lazy="raise",
    )
    parent: Mapped[Message | None] = relationship(
        "Message",
        primaryjoin="foreign(Message.parent_message_id) == Message.id",
        remote_side="Message.id",
        passive_deletes=True,
        lazy="raise",
    )

    __table_args__ = (
        # 会话内消息默认按创建时间升序分页
        Index("ix_messages_conversation_id_created_at", "conversation_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Message(role={self.role!r}, conversation_id={self.conversation_id!r})>"
