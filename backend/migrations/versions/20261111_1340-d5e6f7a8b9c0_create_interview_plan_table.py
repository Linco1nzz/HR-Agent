"""create interview plan table

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-11-11 13:40:00.000000+08:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d5e6f7a8b9c0"
down_revision: str | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interview_plan",
        sa.Column("candidate_name", sa.String(length=100), nullable=False, comment="候选人姓名"),
        sa.Column(
            "candidate_position",
            sa.String(length=200),
            nullable=False,
            comment="应聘岗位",
        ),
        sa.Column("content", sa.Text(), nullable=False, comment="面试方案正文"),
        sa.Column(
            "resume_evaluation_id",
            sa.Uuid(),
            nullable=False,
            comment="关联的简历评价 ID",
        ),
        sa.Column("job_title", sa.String(length=255), nullable=True, comment="JD 标题快照"),
        sa.Column("job_description_id", sa.Uuid(), nullable=True, comment="关联 JD ID"),
        sa.Column("conversation_id", sa.String(length=64), nullable=True, comment="Dify 会话 ID"),
        sa.Column(
            "workflow_type",
            sa.String(length=50),
            server_default="interview_plan",
            nullable=False,
            comment="工作流类型",
        ),
        sa.Column(
            "meta_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="附加元数据（如生成要求、task_id）",
        ),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interview_plan")),
    )
    op.create_index(
        op.f("ix_interview_plan_resume_evaluation_id"),
        "interview_plan",
        ["resume_evaluation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_interview_plan_job_description_id"),
        "interview_plan",
        ["job_description_id"],
        unique=False,
    )
    op.create_index(
        "ix_interview_plan_created_at",
        "interview_plan",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_interview_plan_created_at", table_name="interview_plan")
    op.drop_index(op.f("ix_interview_plan_job_description_id"), table_name="interview_plan")
    op.drop_index(op.f("ix_interview_plan_resume_evaluation_id"), table_name="interview_plan")
    op.drop_table("interview_plan")
