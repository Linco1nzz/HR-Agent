"""简历评价记录模型。

一次简历上传对应一条记录：保存文件信息、解析后的简历正文、AI 提取的候选人
信息与评分结果。``job_description_id`` / ``scoring_criteria_id`` 按项目约定不建
数据库外键，关联完整性由业务层保证；评分时会把 JD 与评分标准标题快照到本表，
避免后续源数据改名或删除后历史记录无法展示。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Float, Index, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import BaseModel


class ResumeEvaluation(BaseModel):
    """简历筛选 / 评分记录。"""

    __tablename__ = "resume_evaluation"

    # --- 文件信息 ---
    original_filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="原始文件名",
    )
    file_path: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="简历文件存储路径",
    )
    file_type: Mapped[str] = mapped_column(String(10), nullable=False, comment="文件类型")
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, comment="文件大小（字节）")

    # --- 简历正文 ---
    resume_content: Mapped[str] = mapped_column(Text, nullable=False, comment="解析后的简历文本")

    # --- 候选人信息（由 AI 从简历中提取）---
    candidate_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="候选人姓名",
    )
    candidate_position: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        comment="应聘岗位",
    )
    candidate_age: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="年龄")
    candidate_gender: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        comment="性别",
    )
    work_years: Mapped[float | None] = mapped_column(Float, nullable=True, comment="工作年限")
    education_level: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="学历",
    )
    school: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="毕业院校")

    # --- 评分结果 ---
    total_score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="总分")
    max_score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="评分标准总分")
    evaluation_metrics: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="评分维度列表：name / score / max / reason",
    )
    ai_answer: Mapped[str | None] = mapped_column(Text, nullable=True, comment="AI 原始回答")
    ai_response: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Dify 完整响应（含 usage 等元数据）",
    )

    # --- 状态与关联 ---
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        server_default="pending",
        index=True,
        comment="状态：pending / interview / rejected",
    )
    job_title: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="JD 标题快照")
    job_description_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
        comment="关联 JD ID",
    )
    scoring_criteria_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
        comment="评分标准 ID",
    )
    scoring_criteria_title: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="评分标准标题快照",
    )
    conversation_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="Dify 会话 ID",
    )

    __table_args__ = (Index("ix_resume_evaluation_created_at", "created_at"),)

    def __repr__(self) -> str:
        return (
            f"<ResumeEvaluation(id={self.id!r}, "
            f"candidate_name={self.candidate_name!r}, total_score={self.total_score!r})>"
        )
