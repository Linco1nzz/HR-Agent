"""简历评分标准模型。

评分标准由 HR 根据已保存的 JD 通过 Dify Chatflow 的 type=2 流程生成，生成结果
先返回前端编辑，确认后再保存。正文 ``content`` 保存 Markdown 文本；结构化评分
维度（``scoring_dimensions``）与附加数据（``criteria_data``）使用 PostgreSQL
``JSONB``，便于后续在不迁移表结构的情况下扩展字段。

``job_description_id`` 按项目约定不建数据库外键，关联完整性由业务层校验。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Index, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import BaseModel


class ScoringCriteria(BaseModel):
    """已保存的简历评分标准。"""

    __tablename__ = "scoring_criteria"

    # --- 基本信息 ---
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True, comment="标题")
    job_title: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="职位名称")

    # --- 正文与结构化数据 ---
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="评分标准正文")
    criteria_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="结构化评分标准数据"
    )
    total_score: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="100",
        server_default="100",
        comment="总分",
    )
    scoring_dimensions: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True, comment="评分维度列表"
    )

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
        default="scoring_criteria_generation",
        server_default="scoring_criteria_generation",
        comment="工作流类型",
    )

    # --- 关联的 JD ---
    job_description_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True, comment="职位描述 ID"
    )

    __table_args__ = (
        # 列表默认按更新时间倒序，单列索引避免数据量增长后的全表排序
        Index("ix_scoring_criteria_updated_at", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<ScoringCriteria(title={self.title!r}, status={self.status!r})>"
