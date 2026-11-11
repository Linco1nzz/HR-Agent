"""create resume evaluation table

Revision ID: c4d5e6f7a8b9
Revises: 8b7c6d5e4f3a
Create Date: 2026-11-11 01:00:00.000000+08:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: str | None = "8b7c6d5e4f3a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resume_evaluation",
        sa.Column("original_filename", sa.String(length=255), nullable=False, comment="原始文件名"),
        sa.Column("file_path", sa.String(length=500), nullable=True, comment="简历文件存储路径"),
        sa.Column("file_type", sa.String(length=10), nullable=False, comment="文件类型"),
        sa.Column("file_size", sa.Integer(), nullable=False, comment="文件大小（字节）"),
        sa.Column("resume_content", sa.Text(), nullable=False, comment="解析后的简历文本"),
        sa.Column("candidate_name", sa.String(length=100), nullable=True, comment="候选人姓名"),
        sa.Column("candidate_position", sa.String(length=200), nullable=True, comment="应聘岗位"),
        sa.Column("candidate_age", sa.Integer(), nullable=True, comment="年龄"),
        sa.Column("candidate_gender", sa.String(length=10), nullable=True, comment="性别"),
        sa.Column("work_years", sa.Float(), nullable=True, comment="工作年限"),
        sa.Column("education_level", sa.String(length=100), nullable=True, comment="学历"),
        sa.Column("school", sa.String(length=200), nullable=True, comment="毕业院校"),
        sa.Column("total_score", sa.Float(), nullable=True, comment="总分"),
        sa.Column("max_score", sa.Float(), nullable=True, comment="评分标准总分"),
        sa.Column(
            "evaluation_metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="评分维度列表：name / score / max / reason",
        ),
        sa.Column("ai_answer", sa.Text(), nullable=True, comment="AI 原始回答"),
        sa.Column(
            "ai_response",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Dify 完整响应（含 usage 等元数据）",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
            comment="状态：pending / interview / rejected",
        ),
        sa.Column("job_title", sa.String(length=255), nullable=True, comment="JD 标题快照"),
        sa.Column("job_description_id", sa.Uuid(), nullable=False, comment="关联 JD ID"),
        sa.Column("scoring_criteria_id", sa.Uuid(), nullable=False, comment="评分标准 ID"),
        sa.Column(
            "scoring_criteria_title",
            sa.String(length=255),
            nullable=True,
            comment="评分标准标题快照",
        ),
        sa.Column("conversation_id", sa.String(length=64), nullable=True, comment="Dify 会话 ID"),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resume_evaluation")),
    )
    op.create_index(
        op.f("ix_resume_evaluation_job_description_id"),
        "resume_evaluation",
        ["job_description_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_resume_evaluation_scoring_criteria_id"),
        "resume_evaluation",
        ["scoring_criteria_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_resume_evaluation_status"),
        "resume_evaluation",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_resume_evaluation_created_at",
        "resume_evaluation",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_resume_evaluation_created_at", table_name="resume_evaluation")
    op.drop_index(op.f("ix_resume_evaluation_status"), table_name="resume_evaluation")
    op.drop_index(op.f("ix_resume_evaluation_scoring_criteria_id"), table_name="resume_evaluation")
    op.drop_index(op.f("ix_resume_evaluation_job_description_id"), table_name="resume_evaluation")
    op.drop_table("resume_evaluation")
