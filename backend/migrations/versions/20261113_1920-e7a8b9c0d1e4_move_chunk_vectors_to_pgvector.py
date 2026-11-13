"""move chunk vectors to langchain pgvector

Revision ID: e7a8b9c0d1e4
Revises: e7a8b9c0d1e3
Create Date: 2026-11-13 19:20:00.000000+08:00

分块向量改由 LangChain PGVector 管理，统一存入 ``langchain_pg_embedding`` 表
（该表由 PGVector 在首次使用时惰性创建，不由 Alembic 管理）。因此移除自建的
``document_chunks`` 表与 ``documents.embedding`` 文档级向量列。

注意：升级会丢弃已有分块向量与文档级向量；如需保留，请对相应文档调用
``POST /documents/{id}/reprocess`` 重新切块并向量化。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e7a8b9c0d1e4"
down_revision: str | None = "e7a8b9c0d1e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: 与 settings.embedding_dim 的默认值保持一致
EMBEDDING_DIM = 1024


def upgrade() -> None:
    op.drop_index(op.f("ix_document_chunks_document_id"), table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_column("documents", "embedding")


def downgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True, comment="文档语义向量"),
    )
    op.create_table(
        "document_chunks",
        sa.Column("document_id", sa.Uuid(), nullable=False, comment="所属文档 ID"),
        sa.Column("chunk_index", sa.Integer(), nullable=False, comment="分块序号，从 0 开始"),
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
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True, comment="分块语义向量"),
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
