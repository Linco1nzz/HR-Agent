"""面试方案模型。

面试方案由 HR 在简历筛选页针对某份已评分的简历通过 Dify Chatflow type=4 生成，
生成结果先返回前端预览 / 编辑，确认后再保存。``resume_evaluation_id`` 与
``job_description_id`` 按项目约定不建数据库外键，关联完整性由业务层校验；保存时
会把候选人信息与 JD 标题快照到本表，避免源记录后续变化影响历史方案展示。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Index, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import BaseModel


class InterviewPlan(BaseModel):
    """候选人的面试方案。"""

    __tablename__ = "interview_plan"

    # --- 候选人信息（保存时快照）---
    candidate_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="候选人姓名",
    )
    candidate_position: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="应聘岗位",
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="面试方案正文")

    # --- 关联记录 ---
    resume_evaluation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
        comment="关联的简历评价 ID",
    )
    job_title: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="JD 标题快照")
    job_description_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        index=True,
        comment="关联 JD ID",
    )

    # --- 生成信息 ---
    conversation_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="Dify 会话 ID",
    )
    workflow_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="interview_plan",
        server_default="interview_plan",
        comment="工作流类型",
    )
    meta_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="附加元数据（如生成要求、task_id）",
    )

    __table_args__ = (Index("ix_interview_plan_created_at", "created_at"),)

    def __repr__(self) -> str:
        return (
            f"<InterviewPlan(id={self.id!r}, "
            f"candidate_name={self.candidate_name!r}, "
            f"resume_evaluation_id={self.resume_evaluation_id!r})>"
        )
