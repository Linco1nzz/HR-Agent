"""Agent 异步任务模型。

一条用户指令对应一个 ``AgentTask``：任务脱离 HTTP 上下文由 Worker 执行，
步骤计划、确认请求与执行进度以 JSONB 快照落在本表；真正的业务数据（JD、
评分标准、面试方案、简历评估）仍由各自 service 读写。按项目约定不建数据库
外键，``conversation_id`` / ``user_id`` 的关联完整性由业务层保证。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Integer, String, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import BaseModel


class AgentTask(BaseModel):
    """HR Agent 任务：状态机 + 步骤计划 + 待确认动作。"""

    __tablename__ = "agent_tasks"

    # --- 归属 ---
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
        comment="所属会话 ID",
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
        comment="发起任务的用户 ID",
    )

    # --- 状态 ---
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="created",
        server_default="created",
        comment="任务状态：created / running / waiting_confirm / completed / failed / cancelled",
    )
    instruction: Mapped[str] = mapped_column(Text, nullable=False, comment="用户原始指令")
    current_step_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="当前执行到的步骤下标",
    )

    # --- 快照 ---
    steps: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
        comment="步骤计划与执行进度快照",
    )
    pending_confirm: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="待用户确认的动作（工具名、参数、摘要）",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="任务失败原因",
    )

    def __repr__(self) -> str:
        return f"<AgentTask(status={self.status!r}, conversation_id={self.conversation_id!r})>"
