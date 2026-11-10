"""简历评分标准相关的请求 / 响应模型。

字段与 ``app.db.models.scoring_criteria.ScoringCriteria`` 对齐；生成接口只返回
结果、不落库，前端编辑后再调用创建 / 更新接口保存。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.ai import ChatUsage

WORKFLOW_TYPE = "scoring_criteria_generation"


class ScoringCriteriaStatus(StrEnum):
    """评分标准状态。"""

    DRAFT = "draft"
    GENERATED = "generated"
    PUBLISHED = "published"
    ARCHIVED = "archived"


def _strip_required(value: str, label: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{label}不能为空")
    return stripped


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def _normalize_dimensions(
    value: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    """去掉值为空字符串 / None 的维度字段，并丢弃空维度。"""
    if value is None:
        return None
    normalized: list[dict[str, Any]] = []
    for item in value:
        cleaned = {
            key: item_value for key, item_value in item.items() if item_value not in (None, "")
        }
        if cleaned:
            normalized.append(cleaned)
    return normalized or None


class ScoringCriteriaBase(BaseModel):
    """评分标准的公共字段（创建与读取共用）。"""

    title: str = Field(min_length=1, max_length=255, description="标题")
    job_title: str | None = Field(default=None, max_length=255, description="职位名称")
    content: str = Field(min_length=1, description="评分标准正文")
    criteria_data: dict[str, Any] | None = Field(default=None, description="结构化评分标准数据")
    total_score: str = Field(default="100", max_length=20, description="总分")
    scoring_dimensions: list[dict[str, Any]] | None = Field(
        default=None, description="评分维度列表"
    )
    status: ScoringCriteriaStatus = Field(default=ScoringCriteriaStatus.DRAFT, description="状态")
    meta_data: dict[str, Any] | None = Field(default=None, description="附加元数据")
    conversation_id: str | None = Field(default=None, max_length=64, description="会话 ID")
    workflow_type: str = Field(
        default=WORKFLOW_TYPE,
        max_length=50,
        description="工作流类型",
    )
    job_description_id: UUID | None = Field(default=None, description="职位描述 ID")

    @field_validator("title")
    @classmethod
    def _validate_title(cls, value: str) -> str:
        return _strip_required(value, "标题")

    @field_validator("job_title")
    @classmethod
    def _clean_job_title(cls, value: str | None) -> str | None:
        return _strip_optional(value)

    @field_validator("content")
    @classmethod
    def _validate_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("评分标准内容不能为空")
        return value

    @field_validator("total_score")
    @classmethod
    def _validate_total_score(cls, value: str) -> str:
        return _strip_required(value, "总分")

    @field_validator("scoring_dimensions")
    @classmethod
    def _clean_dimensions(cls, value: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        return _normalize_dimensions(value)


class ScoringCriteriaCreate(ScoringCriteriaBase):
    """创建评分标准。"""


class ScoringCriteriaUpdate(BaseModel):
    """局部更新评分标准；只修改请求中显式出现的字段。"""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    job_title: str | None = Field(default=None, max_length=255)
    content: str | None = Field(default=None, min_length=1)
    criteria_data: dict[str, Any] | None = None
    total_score: str | None = Field(default=None, max_length=20)
    scoring_dimensions: list[dict[str, Any]] | None = None
    status: ScoringCriteriaStatus | None = None
    meta_data: dict[str, Any] | None = None
    conversation_id: str | None = Field(default=None, max_length=64)
    workflow_type: str | None = Field(default=None, max_length=50)
    job_description_id: UUID | None = None

    @field_validator("title")
    @classmethod
    def _validate_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _strip_required(value, "标题")

    @field_validator("job_title")
    @classmethod
    def _clean_job_title(cls, value: str | None) -> str | None:
        return _strip_optional(value)

    @field_validator("content")
    @classmethod
    def _validate_content(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("评分标准内容不能为空")
        return value

    @field_validator("total_score")
    @classmethod
    def _validate_total_score(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _strip_required(value, "总分")

    @field_validator("scoring_dimensions")
    @classmethod
    def _clean_dimensions(cls, value: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        return _normalize_dimensions(value)


class ScoringCriteriaRead(ScoringCriteriaBase):
    """评分标准详情。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="评分标准 ID")
    created_by: UUID | None = Field(default=None, description="创建人 ID")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class ScoringCriteriaListItem(BaseModel):
    """评分标准列表项（不返回完整正文与结构化数据）。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="评分标准 ID")
    title: str = Field(description="标题")
    job_title: str | None = Field(default=None, description="职位名称")
    total_score: str = Field(description="总分")
    status: ScoringCriteriaStatus = Field(description="状态")
    job_description_id: UUID | None = Field(default=None, description="职位描述 ID")
    dimension_count: int = Field(default=0, description="评分维度数量")
    content_preview: str = Field(description="正文摘要")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class ScoringCriteriaListResponse(BaseModel):
    """评分标准分页列表。"""

    items: list[ScoringCriteriaListItem] = Field(default_factory=list, description="评分标准列表")
    total: int = Field(description="总数")
    page: int = Field(description="当前页")
    page_size: int = Field(description="每页数量")


class GenerateScoringCriteriaRequest(BaseModel):
    """根据已有 JD 生成简历评分标准（不落库，由前端确认后再保存）。"""

    job_description_id: UUID = Field(description="已保存的 JD ID")
    title: str | None = Field(default=None, max_length=255, description="标题（可选）")
    total_score: str = Field(default="100", max_length=20, description="总分")
    instructions: str | None = Field(
        default=None,
        max_length=2_000,
        description="额外生成要求（可选）",
    )

    @field_validator("title")
    @classmethod
    def _clean_title(cls, value: str | None) -> str | None:
        return _strip_optional(value)

    @field_validator("total_score")
    @classmethod
    def _validate_total_score(cls, value: str) -> str:
        return _strip_required(value, "总分")

    @field_validator("instructions")
    @classmethod
    def _clean_instructions(cls, value: str | None) -> str | None:
        return _strip_optional(value)


class GenerateScoringCriteriaResponse(BaseModel):
    """AI 生成简历评分标准的结果。"""

    title: str = Field(description="建议标题")
    job_title: str | None = Field(default=None, description="职位名称")
    content: str = Field(description="生成的评分标准正文（Markdown）")
    total_score: str = Field(default="100", description="总分")
    scoring_dimensions: list[dict[str, Any]] | None = Field(
        default=None, description="评分维度列表"
    )
    criteria_data: dict[str, Any] | None = Field(default=None, description="结构化评分标准数据")
    job_description_id: UUID | None = Field(default=None, description="职位描述 ID")
    conversation_id: str = Field(default="", description="Dify 会话 ID")
    workflow_type: str = Field(default=WORKFLOW_TYPE, description="工作流类型")
    task_id: str = Field(default="", description="Dify 任务 ID")
    usage: ChatUsage | None = Field(default=None, description="token / 计费信息")


__all__ = [
    "GenerateScoringCriteriaRequest",
    "GenerateScoringCriteriaResponse",
    "ScoringCriteriaCreate",
    "ScoringCriteriaListItem",
    "ScoringCriteriaListResponse",
    "ScoringCriteriaRead",
    "ScoringCriteriaStatus",
    "ScoringCriteriaUpdate",
]
