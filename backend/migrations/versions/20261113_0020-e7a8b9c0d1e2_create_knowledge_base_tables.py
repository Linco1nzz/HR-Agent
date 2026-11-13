"""create knowledge base tables

Revision ID: e7a8b9c0d1e2
Revises: d5e6f7a8b9c0
Create Date: 2026-11-13 00:20:00.000000+08:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e7a8b9c0d1e2"
down_revision: str | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: 建表时的默认向量维度；后续迁移会按实际 embedding 模型调整
EMBEDDING_DIM = 1536


def _base_columns() -> list[sa.Column]:
    """BaseModel 提供的公共列。"""
    return [
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            comment="主键",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="更新时间",
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True, comment="创建人 ID"),
        sa.Column("updated_by", sa.Uuid(), nullable=True, comment="更新人 ID"),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
            comment="是否启用",
        ),
    ]


def upgrade() -> None:
    # 向量列依赖 pgvector；已有数据卷可能没有执行过初始化脚本
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "knowledge_bases",
        sa.Column("name", sa.String(length=255), nullable=False, comment="知识库名称"),
        sa.Column("description", sa.Text(), nullable=True, comment="知识库描述"),
        sa.Column(
            "is_public",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="是否公开",
        ),
        sa.Column(
            "is_searchable",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
            comment="是否允许搜索",
        ),
        sa.Column(
            "meta_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="知识库扩展元数据",
        ),
        sa.Column(
            "document_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="文档数量",
        ),
        sa.Column("category", sa.String(length=100), nullable=True, comment="知识库分类"),
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="知识库标签列表",
        ),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_bases")),
    )
    op.create_index(
        op.f("ix_knowledge_bases_name"),
        "knowledge_bases",
        ["name"],
        unique=True,
    )

    op.create_table(
        "documents",
        sa.Column("filename", sa.String(length=255), nullable=False, comment="存储文件名"),
        sa.Column(
            "original_filename",
            sa.String(length=255),
            nullable=False,
            comment="原始文件名",
        ),
        sa.Column("file_path", sa.String(length=500), nullable=False, comment="文件存储路径"),
        sa.Column("file_size", sa.Integer(), nullable=False, comment="文件大小，单位字节"),
        sa.Column("file_hash", sa.String(length=64), nullable=False, comment="文件 SHA256 哈希值"),
        sa.Column("mime_type", sa.String(length=100), nullable=False, comment="文件 MIME 类型"),
        sa.Column("extracted_content", sa.Text(), nullable=True, comment="文件解析后的文本内容"),
        sa.Column(
            "meta_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="文档扩展元数据",
        ),
        sa.Column(
            "processing_status",
            sa.String(length=20),
            server_default="uploaded",
            nullable=False,
            comment="处理状态：uploaded / processing / processed / failed",
        ),
        sa.Column("processing_error", sa.Text(), nullable=True, comment="处理失败原因"),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="处理完成时间",
        ),
        sa.Column(
            "chunk_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="有效分块数量",
        ),
        sa.Column(
            "embedding",
            Vector(EMBEDDING_DIM),
            nullable=True,
            comment="文档语义向量",
        ),
        sa.Column("category", sa.String(length=100), nullable=True, comment="文档分类"),
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="文档标签列表",
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False, comment="上传用户 ID"),
        sa.Column(
            "knowledge_base_id",
            sa.Uuid(),
            nullable=True,
            comment="所属知识库 ID；删除知识库后置空",
        ),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    op.create_index(op.f("ix_documents_file_hash"), "documents", ["file_hash"], unique=False)
    op.create_index(
        op.f("ix_documents_processing_status"),
        "documents",
        ["processing_status"],
        unique=False,
    )
    op.create_index(op.f("ix_documents_user_id"), "documents", ["user_id"], unique=False)
    op.create_index(
        op.f("ix_documents_knowledge_base_id"),
        "documents",
        ["knowledge_base_id"],
        unique=False,
    )
    op.create_index(
        "ix_documents_knowledge_base_created_at",
        "documents",
        ["knowledge_base_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "document_chunks",
        sa.Column("document_id", sa.Uuid(), nullable=False, comment="所属文档 ID"),
        sa.Column(
            "chunk_index",
            sa.Integer(),
            nullable=False,
            comment="分块序号，从 0 开始",
        ),
        sa.Column("content", sa.Text(), nullable=False, comment="分块文本"),
        sa.Column(
            "char_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="分块字符数",
        ),
        sa.Column(
            "meta_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="分块扩展元数据",
        ),
        sa.Column(
            "embedding",
            Vector(EMBEDDING_DIM),
            nullable=True,
            comment="分块语义向量",
        ),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_chunks")),
        sa.UniqueConstraint(
            "document_id",
            "chunk_index",
            name=op.f("uq_document_chunks_document_id_chunk_index"),
        ),
    )
    op.create_index(
        op.f("ix_document_chunks_document_id"),
        "document_chunks",
        ["document_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_document_chunks_document_id"), table_name="document_chunks")
    op.drop_table("document_chunks")

    op.drop_index("ix_documents_knowledge_base_created_at", table_name="documents")
    op.drop_index(op.f("ix_documents_knowledge_base_id"), table_name="documents")
    op.drop_index(op.f("ix_documents_user_id"), table_name="documents")
    op.drop_index(op.f("ix_documents_processing_status"), table_name="documents")
    op.drop_index(op.f("ix_documents_file_hash"), table_name="documents")
    op.drop_table("documents")

    op.drop_index(op.f("ix_knowledge_bases_name"), table_name="knowledge_bases")
    op.drop_table("knowledge_bases")
