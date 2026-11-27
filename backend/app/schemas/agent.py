"""HR Agent 接口的请求 / 响应模型。

任务、步骤与确认动作的字段与 ``app.db.models.agent_task.AgentTask`` 的 JSONB
快照一致；SSE 事件载荷由 :mod:`app.services.agent.events` 负责组装。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AgentTaskStatus(StrEnum):
    """任务状态。"""

    CREATED = "created"
    RUNNING = "running"
    WAITING_CONFIRM = "waiting_confirm"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentStepStatus(StrEnum):
    """步骤状态。"""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_CONFIRM = "waiting_confirm"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class AgentConfirmAction(StrEnum):
    """确认动作：执行 / 取消。"""

    CONFIRM = "confirm"
    CANCEL = "cancel"


#: 任务终态，用于判断是否还需要保持 SSE 连接
TERMINAL_TASK_STATUSES: frozenset[AgentTaskStatus] = frozenset(
    {AgentTaskStatus.COMPLETED, AgentTaskStatus.FAILED, AgentTaskStatus.CANCELLED}
)


class AgentStepRead(BaseModel):
    """一个步骤的执行快照。"""

    step_index: int = Field(description="步骤下标（从 0 开始）")
    tool: str = Field(description="工具名")
    name: str = Field(description="工具中文名")
    status: AgentStepStatus = Field(description="步骤状态")
    args: dict[str, Any] = Field(default_factory=dict, description="工具参数")
    summary: str = Field(default="", description="步骤摘要")
    result_preview: str | None = Field(default=None, description="结果摘要（列表展示用）")
    content: str | None = Field(default=None, description="生成类步骤的完整结果")
    error: str | None = Field(default=None, description="步骤失败原因")
    editable: bool = Field(default=False, description="确认时是否允许修改参数")


class AgentConfirmRead(BaseModel):
    """待确认动作。"""

    step_index: int = Field(description="待确认步骤下标")
    tool: str = Field(description="工具名")
    name: str = Field(description="工具中文名")
    summary: str = Field(description="确认摘要")
    args: dict[str, Any] = Field(default_factory=dict, description="当前参数")
    editable: bool = Field(default=False, description="是否允许修改参数后确认")


class AgentTaskRead(BaseModel):
    """任务详情（SSE 首帧与刷新恢复共用）。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="任务 ID")
    conversation_id: UUID = Field(description="会话 ID")
    status: AgentTaskStatus = Field(description="任务状态")
    instruction: str = Field(description="用户原始指令")
    current_step_index: int = Field(default=0, description="当前步骤下标")
    steps: list[AgentStepRead] = Field(default_factory=list, description="步骤计划与进度")
    pending_confirm: AgentConfirmRead | None = Field(default=None, description="待确认动作")
    error_message: str | None = Field(default=None, description="失败原因")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class AgentChatRequest(BaseModel):
    """发起一条 Agent 指令。"""

    conversation_id: UUID = Field(description="Agent 会话 ID")
    content: str = Field(min_length=1, max_length=4_000, description="自然语言指令")

    @field_validator("content")
    @classmethod
    def _strip_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("指令内容不能为空")
        return stripped


class AgentChatResponse(BaseModel):
    """创建任务后的立即响应（不等 Dify 返回）。"""

    task_id: UUID = Field(description="任务 ID，用于订阅 SSE")
    status: AgentTaskStatus = Field(description="任务初始状态")


class AgentConfirmRequest(BaseModel):
    """确认或取消一个挂起的写操作。"""

    task_id: UUID = Field(description="任务 ID")
    action: AgentConfirmAction = Field(description="confirm 执行 / cancel 取消")
    params: dict[str, Any] | None = Field(
        default=None,
        description="确认时提交的修改后参数（可编辑卡片）；缺省沿用原参数",
    )


class AgentConfirmResponse(BaseModel):
    """确认后的立即响应（Worker 在后台续跑）。"""

    task_id: UUID = Field(description="任务 ID")
    status: AgentTaskStatus = Field(description="任务当前状态")


class AgentResumeUploadResponse(BaseModel):
    """确认表单内上传简历的响应（只解析，不评分）。"""

    upload_id: str = Field(description="上传标识，提交给 score_resume 使用")
    filename: str = Field(description="原始文件名")
    resume_chars: int = Field(description="解析出的简历文本长度")
