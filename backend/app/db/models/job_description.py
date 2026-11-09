"""职位描述（JD）模型。

JD 由 HR 手动创建或通过 Dify Chatflow 的 type=1 流程生成后保存。技能列表与
附加元数据使用 PostgreSQL ``JSONB``，便于后续扩展结构化字段，无需频繁迁移。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import BaseModel


class JobDescription(BaseModel):
    """已保存的职位描述。"""

    __tablename__ = "job_description"

    # --- 基本信息 ---
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True, comment="标题")
    department: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="所属部门")
    location: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="工作地点")
    salary_range: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="薪资范围")
    experience_level: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="经验等级"
    )
    education: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="学历要求")
    job_type: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="工作类型")

    # --- 技能与正文 ---
    skills: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True, comment="技能要求列表")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="职位描述正文")
    requirements: Mapped[str | None] = mapped_column(Text, nullable=True, comment="职位要求")

    # --- 状态与生成信息 ---
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        server_default="draft",
        index=True,
        comment="状态：draft / generated / published / archived",
    )
    meta_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="附加元数据"
    )
    conversation_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Dify 会话 ID"
    )
    workflow_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="jd_generation",
        server_default="jd_generation",
        comment="工作流类型",
    )

    __table_args__ = (
        # 列表默认按更新时间倒序，单列索引避免数据量增长后的全表排序
        Index("ix_job_description_updated_at", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<JobDescription(title={self.title!r}, status={self.status!r})>"
