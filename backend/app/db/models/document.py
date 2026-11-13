"""知识库文档模型。

:class:`Document` 保存上传文件的信息、解析后的正文与处理状态。分块文本与
向量不再落在业务表，而是统一存入 LangChain PGVector 的 ``langchain_pg_embedding``
表（见 :mod:`app.services.vector_store_service`），按 ``cmetadata.document_id``
关联到本文档。

按项目约定不建数据库外键，``knowledge_base_id`` / ``user_id`` 的关联完整性
由业务层保证；删除文档时由业务层一并清理 PGVector 中对应的分块向量。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import DateTime, Index, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel

if TYPE_CHECKING:
    from app.db.models.knowledge_base import KnowledgeBase
    from app.db.models.user import User


class Document(BaseModel):
    """知识库中的一份文档。"""

    __tablename__ = "documents"

    # --- 基本信息 ---
    filename: Mapped[str] = mapped_column(String(255), nullable=False, comment="存储文件名")
    original_filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="原始文件名",
    )
    file_path: Mapped[str] = mapped_column(String(500), nullable=False, comment="文件存储路径")
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, comment="文件大小，单位字节")
    file_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="文件 SHA256 哈希值",
    )
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False, comment="文件 MIME 类型")

    # --- 内容和元数据 ---
    extracted_content: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="文件解析后的文本内容",
    )
    meta_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="文档扩展元数据",
    )
    processing_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="uploaded",
        server_default="uploaded",
        index=True,
        comment="处理状态：uploaded / processing / processed / failed",
    )
    processing_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="处理失败原因",
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="处理完成时间",
    )
    chunk_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="有效分块数量",
    )

    # --- 分类 ---
    category: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="文档分类")
    tags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True, comment="文档标签列表")

    # --- 关系 ---
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
        comment="上传用户 ID",
    )
    knowledge_base_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        index=True,
        comment="所属知识库 ID；删除知识库后置空",
    )

    knowledge_base: Mapped[KnowledgeBase | None] = relationship(
        "KnowledgeBase",
        primaryjoin="foreign(Document.knowledge_base_id) == KnowledgeBase.id",
        back_populates="documents",
        lazy="raise",
    )
    uploaded_by: Mapped[User] = relationship(
        "User",
        primaryjoin="foreign(Document.user_id) == User.id",
        back_populates="documents",
        lazy="raise",
    )

    __table_args__ = (
        # 知识库详情默认按创建时间倒序列出文档
        Index("ix_documents_knowledge_base_created_at", "knowledge_base_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<Document(original_filename={self.original_filename!r}, "
            f"status={self.processing_status!r})>"
        )
