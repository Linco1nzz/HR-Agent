"""alter embedding dimension to qwen3.7-text-embedding

Revision ID: e7a8b9c0d1e3
Revises: e7a8b9c0d1e2
Create Date: 2026-11-13 17:00:00.000000+08:00

阿里云百炼 qwen3.7-text-embedding 输出 1024 维向量，把文档与分块两张表的
向量列从 1536 调整为 1024。

维度变化无法直接 cast：升级前先把已有向量置空（旧的 1536 维向量与新模型
不兼容），需要时对文档调用重新处理接口重建向量。
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7a8b9c0d1e3"
down_revision: str | None = "e7a8b9c0d1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_DIMENSION = 1536
_NEW_DIMENSION = 1024


def _alter_columns(dimension: int) -> None:
    for table in ("documents", "document_chunks"):
        # 维度变化不能直接 cast，先清空旧向量
        op.execute(f"UPDATE {table} SET embedding = NULL WHERE embedding IS NOT NULL")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN embedding TYPE vector({dimension})")


def upgrade() -> None:
    _alter_columns(_NEW_DIMENSION)


def downgrade() -> None:
    _alter_columns(_OLD_DIMENSION)
