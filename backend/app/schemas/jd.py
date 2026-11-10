"""JD（职位描述）相关的请求 / 响应模型。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.ai import ChatUsage


class JDStatus(StrEnum):
    """JD 状态。"""

    DRAFT = "draft"
    GENERATED = "generated"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class JDBase(BaseModel):
    """JD 的公共字段（创建与读取共用）。"""

    title: str = Field(min_length=1, max_length=255, description="标题")
    department: str | None = Field(default=None, max_length=100, description="所属部门")
    location: str | None = Field(default=None, max_length=100, description="工作地点")
    salary_range: str | None = Field(default=None, max_length=100, description="薪资范围")
    experience_level: str | None = Field(default=None, max_length=100, description="经验等级")
    education: str | None = Field(default=None, max_length=100, description="学历要求")
    job_type: str | None = Field(default=None, max_length=100, description="工作类型")
    skills: list[str] | None = Field(default=None, description="技能要求列表")
    content: str = Field(min_length=1, description="职位描述正文")
    requirements: str | None = Field(default=None, description="职位要求")
    status: JDStatus = Field(default=JDStatus.DRAFT, description="状态")
    meta_data: dict[str, Any] | None = Field(default=None, description="附加元数据")
    conversation_id: str | None = Field(default=None, max_length=64, description="会话 ID")
    workflow_type: str = Field(
        default="jd_generation",
        max_length=50,
        description="工作流类型",
    )

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("标题不能为空")
        return stripped

    @field_validator("content")
    @classmethod
    def _validate_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("JD 内容不能为空")
        return value

    @field_validator("skills")
    @classmethod
    def _normalize_skills(cls, value: list[str] | None) -> list[str] | None:
        """去掉空白技能、去重并保持原顺序。"""
        if value is None:
            return None
        seen: set[str] = set()
        normalized: list[str] = []
        for skill in value:
            item = skill.strip()
            if item and item not in seen:
                seen.add(item)
                normalized.append(item)
        return normalized


class JobDescriptionCreate(JDBase):
    """创建 JD。"""


class JobDescriptionUpdate(BaseModel):
    """局部更新 JD；只修改请求中显式出现的字段。"""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    department: str | None = Field(default=None, max_length=100)
    location: str | None = Field(default=None, max_length=100)
    salary_range: str | None = Field(default=None, max_length=100)
    experience_level: str | None = Field(default=None, max_length=100)
    education: str | None = Field(default=None, max_length=100)
    job_type: str | None = Field(default=None, max_length=100)
    skills: list[str] | None = None
    content: str | None = Field(default=None, min_length=1)
    requirements: str | None = None
    status: JDStatus | None = None
    meta_data: dict[str, Any] | None = None
    conversation_id: str | None = Field(default=None, max_length=64)
    workflow_type: str | None = Field(default=None, max_length=50)

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("标题不能为空")
        return stripped

    @field_validator("content")
    @classmethod
    def _validate_content(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("JD 内容不能为空")
        return value

    @field_validator("skills")
    @classmethod
    def _normalize_skills(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        seen: set[str] = set()
        normalized: list[str] = []
        for skill in value:
            item = skill.strip()
            if item and item not in seen:
                seen.add(item)
                normalized.append(item)
        return normalized


class JobDescriptionRead(JDBase):
    """JD 详情。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="JD ID")
    created_by: UUID | None = Field(default=None, description="创建人 ID")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class JobDescriptionListItem(BaseModel):
    """JD 列表项（不返回完整正文，减少列表响应体）。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="JD ID")
    title: str = Field(description="标题")
    department: str | None = Field(default=None, description="所属部门")
    location: str | None = Field(default=None, description="工作地点")
    salary_range: str | None = Field(default=None, description="薪资范围")
    experience_level: str | None = Field(default=None, description="经验等级")
    education: str | None = Field(default=None, description="学历要求")
    job_type: str | None = Field(default=None, description="工作类型")
    skills: list[str] | None = Field(default=None, description="技能要求列表")
    status: JDStatus = Field(description="状态")
    criteria_count: int = Field(default=0, description="该 JD 的简历评分标准数量")
    content_preview: str = Field(description="正文摘要")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class JobDescriptionListResponse(BaseModel):
    """JD 分页列表。"""

    items: list[JobDescriptionListItem] = Field(default_factory=list, description="JD 列表")
    total: int = Field(description="总数")
    page: int = Field(description="当前页")
    page_size: int = Field(description="每页数量")


class GenerateJDRequest(BaseModel):
    """根据表单信息生成 JD（不落库，由前端确认后再保存）。"""

    title: str = Field(min_length=1, max_length=255, description="职位名称")
    department: str | None = Field(default=None, max_length=100, description="所属部门")
    location: str | None = Field(default=None, max_length=100, description="工作地点")
    salary_range: str | None = Field(default=None, max_length=100, description="薪资范围")
    experience_level: str | None = Field(default=None, max_length=100, description="经验等级")
    education: str | None = Field(default=None, max_length=100, description="学历要求")
    job_type: str | None = Field(default=None, max_length=100, description="工作类型")
    skills: list[str] | None = Field(default=None, description="技能要求列表")
    requirements: str | None = Field(
        default=None,
        max_length=5_000,
        description="职位要求 / 补充说明",
    )

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("职位名称不能为空")
        return stripped

    @field_validator("skills")
    @classmethod
    def _normalize_skills(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return [item.strip() for item in value if item.strip()]


class GenerateJDResponse(BaseModel):
    """AI 生成 JD 的结果。"""

    content: str = Field(description="生成的 JD 正文（Markdown）")
    conversation_id: str = Field(default="", description="Dify 会话 ID")
    workflow_type: str = Field(default="jd_generation", description="工作流类型")
    task_id: str = Field(default="", description="Dify 任务 ID")
    usage: ChatUsage | None = Field(default=None, description="token / 计费信息")
