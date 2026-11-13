"""知识库模型。

一个知识库下可以挂多份文档。按项目约定不建数据库外键，``documents`` 关系
使用显式 join 条件，关联完整性由业务层保证：删除知识库时把文档的
``knowledge_base_id`` 置空（文档、文件与向量块都保留），只有删除文档时才
清理文件、文档记录与向量块。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, Integer, String, Text, false, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel

if TYPE_CHECKING:
    from app.db.models.document import Document


class KnowledgeBase(BaseModel):
    """知识库：一组文档的分类容器。"""

    __tablename__ = "knowledge_bases"

    # --- 基本信息 ---
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
        comment="知识库名称",
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="知识库描述")

    # --- 配置 ---
    is_public: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=false(),
        nullable=False,
        comment="是否公开",
    )
    is_searchable: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=true(),
        nullable=False,
        comment="是否允许搜索",
    )

    # --- 元数据 ---
    meta_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="知识库扩展元数据",
    )
    document_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        comment="文档数量",
    )

    # --- 分类 ---
    category: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="知识库分类",
    )
    tags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True, comment="知识库标签列表")

    # --- 关系：一个知识库下可以有多个文档 ---
    #: ``lazy="raise"``：异步上下文禁止隐式懒加载，需要时显式 ``selectinload``
    documents: Mapped[list[Document]] = relationship(
        "Document",
        primaryjoin="KnowledgeBase.id == foreign(Document.knowledge_base_id)",
        back_populates="knowledge_base",
        lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<KnowledgeBase(name={self.name!r}, documents={self.document_count!r})>"
