"""create agent task table

Revision ID: a7c9e1f3b2d4
Revises: e818b71c0c19
Create Date: 2026-11-24 21:00:00.000000+08:00

HR Agent：``conversations`` 新增 ``kind`` 区分知识问答（knowledge）与 Agent 会话
（agent），并新增 ``agent_tasks`` 表承载任务状态机、步骤计划与待确认动作。按项目
约定不建数据库外键，``conversation_id`` / ``user_id`` 的关联完整性由业务层保证。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a7c9e1f3b2d4"
down_revision: str | None = "e818b71c0c19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "kind",
            sa.String(length=20),
            server_default="knowledge",
            nullable=False,
            comment="会话类型：knowledge（知识问答）/ agent（HR Agent）",
        ),
    )
    op.create_table(
        "agent_tasks",
        sa.Column("conversation_id", sa.Uuid(), nullable=False, comment="所属会话 ID"),
        sa.Column("user_id", sa.Uuid(), nullable=False, comment="发起任务的用户 ID"),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="created",
            nullable=False,
            comment="任务状态：created / running / waiting_confirm / completed / failed / cancelled",
        ),
        sa.Column("instruction", sa.Text(), nullable=False, comment="用户原始指令"),
        sa.Column(
            "current_step_index",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="当前执行到的步骤下标",
        ),
        sa.Column(
            "steps",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment="步骤计划与执行进度快照",
        ),
        sa.Column(
            "pending_confirm",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="待用户确认的动作（工具名、参数、摘要）",
        ),
        sa.Column("error_message", sa.Text(), nullable=True, comment="任务失败原因"),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_tasks")),
    )
    op.create_index(
        op.f("ix_agent_tasks_conversation_id"),
        "agent_tasks",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(op.f("ix_agent_tasks_user_id"), "agent_tasks", ["user_id"], unique=False)
    op.create_index(op.f("ix_agent_tasks_status"), "agent_tasks", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_agent_tasks_status"), table_name="agent_tasks")
    op.drop_index(op.f("ix_agent_tasks_user_id"), table_name="agent_tasks")
    op.drop_index(op.f("ix_agent_tasks_conversation_id"), table_name="agent_tasks")
    op.drop_table("agent_tasks")
    op.drop_column("conversations", "kind")
