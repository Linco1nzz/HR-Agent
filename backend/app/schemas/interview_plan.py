"""智能面试方案相关的请求与响应模型。

面试方案绑定一份简历评价记录，生成时由后端读取该简历与关联 JD 调用 Dify
Chatflow type=4；生成结果不落库，前端确认后再调用创建 / 更新接口保存。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.ai import ChatUsage

WORKFLOW_TYPE = "interview_plan"


class ExportFormat(StrEnum):
    """面试方案导出格式。"""

    DOCX = "docx"
    MARKDOWN = "markdown"


def _strip_required(value: str, label: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{label}不能为空")
    return stripped


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


class InterviewPlanBase(BaseModel):
    """面试方案的公共字段（创建与读取共用）。"""

    candidate_name: str = Field(min_length=1, max_length=100, description="候选人姓名")
    candidate_position: str = Field(min_length=1, max_length=200, description="应聘岗位")
    content: str = Field(min_length=1, description="面试方案正文（Markdown）")
    resume_evaluation_id: UUID = Field(description="关联的简历评价 ID")

    @field_validator("candidate_name")
    @classmethod
    def _validate_candidate_name(cls, value: str) -> str:
        return _strip_required(value, "候选人姓名")

    @field_validator("candidate_position")
    @classmethod
    def _validate_candidate_position(cls, value: str) -> str:
        return _strip_required(value, "应聘岗位")

    @field_validator("content")
    @classmethod
    def _validate_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("面试方案内容不能为空")
        return value


class InterviewPlanCreate(InterviewPlanBase):
    """保存一份新的面试方案。"""

    conversation_id: str | None = Field(default=None, max_length=64, description="Dify 会话 ID")
    meta_data: dict[str, Any] | None = Field(default=None, description="附加元数据")


class InterviewPlanUpdate(BaseModel):
    """局部更新面试方案；只修改请求中显式出现的字段。"""

    candidate_name: str | None = Field(default=None, min_length=1, max_length=100)
    candidate_position: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, min_length=1)

    @field_validator("candidate_name")
    @classmethod
    def _validate_candidate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _strip_required(value, "候选人姓名")

    @field_validator("candidate_position")
    @classmethod
    def _validate_candidate_position(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _strip_required(value, "应聘岗位")

    @field_validator("content")
    @classmethod
    def _validate_content(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("面试方案内容不能为空")
        return value


class InterviewPlanListItem(BaseModel):
    """面试方案列表项（不返回完整正文）。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="面试方案 ID")
    candidate_name: str = Field(description="候选人姓名")
    candidate_position: str = Field(description="应聘岗位")
    resume_evaluation_id: UUID = Field(description="关联的简历评价 ID")
    job_title: str | None = Field(default=None, description="JD 标题")
    content_preview: str = Field(description="正文摘要")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class InterviewPlanRead(InterviewPlanBase):
    """面试方案详情。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="面试方案 ID")
    job_title: str | None = Field(default=None, description="JD 标题")
    job_description_id: UUID | None = Field(default=None, description="关联 JD ID")
    conversation_id: str | None = Field(default=None, description="Dify 会话 ID")
    workflow_type: str = Field(default=WORKFLOW_TYPE, description="工作流类型")
    meta_data: dict[str, Any] | None = Field(default=None, description="附加元数据")
    created_by: UUID | None = Field(default=None, description="创建人 ID")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class InterviewPlanListResponse(BaseModel):
    """面试方案分页列表。"""

    items: list[InterviewPlanListItem] = Field(default_factory=list, description="面试方案列表")
    total: int = Field(description="总数")
    page: int = Field(description="当前页")
    page_size: int = Field(description="每页数量")


class GenerateInterviewPlanRequest(BaseModel):
    """根据简历评价记录生成面试方案（不落库，由前端确认后再保存）。"""

    resume_evaluation_id: UUID = Field(description="已保存的简历评价 ID")
    instructions: str | None = Field(
        default=None,
        max_length=2_000,
        description="额外生成要求（可选），如重点考察方向",
    )

    @field_validator("instructions")
    @classmethod
    def _clean_instructions(cls, value: str | None) -> str | None:
        return _strip_optional(value)


class GenerateInterviewPlanResponse(BaseModel):
    """AI 生成面试方案的结果。"""

    content: str = Field(description="生成的面试方案正文（Markdown）")
    candidate_name: str = Field(description="候选人姓名")
    candidate_position: str = Field(description="应聘岗位")
    resume_evaluation_id: UUID = Field(description="关联的简历评价 ID")
    job_title: str | None = Field(default=None, description="JD 标题")
    job_description_id: UUID | None = Field(default=None, description="关联 JD ID")
    conversation_id: str = Field(default="", description="Dify 会话 ID")
    workflow_type: str = Field(default=WORKFLOW_TYPE, description="工作流类型")
    task_id: str = Field(default="", description="Dify 任务 ID")
    usage: ChatUsage | None = Field(default=None, description="token / 计费信息")


__all__ = [
    "ExportFormat",
    "GenerateInterviewPlanRequest",
    "GenerateInterviewPlanResponse",
    "InterviewPlanCreate",
    "InterviewPlanListItem",
    "InterviewPlanListResponse",
    "InterviewPlanRead",
    "InterviewPlanUpdate",
]
