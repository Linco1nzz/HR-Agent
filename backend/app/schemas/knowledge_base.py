"""知识库相关的请求 / 响应模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _normalize_tags(value: list[str] | None) -> list[str] | None:
    """去掉空白标签、去重并保持原顺序。"""
    if value is None:
        return None
    seen: set[str] = set()
    normalized: list[str] = []
    for tag in value:
        item = tag.strip()
        if item and item not in seen:
            seen.add(item)
            normalized.append(item)
    return normalized


class KnowledgeBaseCreate(BaseModel):
    """创建知识库。"""

    name: str = Field(min_length=1, max_length=255, description="知识库名称")
    description: str | None = Field(default=None, description="知识库描述")
    is_public: bool = Field(default=False, description="是否公开")
    is_searchable: bool = Field(default=True, description="是否允许搜索")
    meta_data: dict[str, Any] | None = Field(default=None, description="扩展元数据")
    category: str | None = Field(default=None, max_length=100, description="知识库分类")
    tags: list[str] | None = Field(default=None, description="标签列表")

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("知识库名称不能为空")
        return stripped

    @field_validator("description", "category")
    @classmethod
    def _strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("tags")
    @classmethod
    def _validate_tags(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_tags(value)


class KnowledgeBaseUpdate(BaseModel):
    """局部更新知识库；只修改请求中显式出现的字段。"""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    is_public: bool | None = None
    is_searchable: bool | None = None
    meta_data: dict[str, Any] | None = None
    category: str | None = Field(default=None, max_length=100)
    tags: list[str] | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("知识库名称不能为空")
        return stripped

    @field_validator("description", "category")
    @classmethod
    def _strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("tags")
    @classmethod
    def _validate_tags(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_tags(value)


class KnowledgeBaseRead(BaseModel):
    """知识库详情。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="知识库 ID")
    name: str = Field(description="知识库名称")
    description: str | None = Field(default=None, description="知识库描述")
    is_public: bool = Field(description="是否公开")
    is_searchable: bool = Field(description="是否允许搜索")
    meta_data: dict[str, Any] | None = Field(default=None, description="扩展元数据")
    document_count: int = Field(default=0, description="文档数量")
    category: str | None = Field(default=None, description="知识库分类")
    tags: list[str] | None = Field(default=None, description="标签列表")
    created_by: UUID | None = Field(default=None, description="创建人 ID")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class KnowledgeBaseListResponse(BaseModel):
    """知识库分页列表。"""

    items: list[KnowledgeBaseRead] = Field(default_factory=list, description="知识库列表")
    total: int = Field(description="总数")
    page: int = Field(description="当前页")
    page_size: int = Field(description="每页数量")
