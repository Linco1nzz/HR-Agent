"""知识库问答会话相关的请求 / 响应模型。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConversationStatus(StrEnum):
    """会话状态。"""

    ACTIVE = "active"
    ARCHIVED = "archived"


class ConversationKind(StrEnum):
    """会话类型：知识问答 / HR Agent。"""

    KNOWLEDGE = "knowledge"
    AGENT = "agent"


class MessageRole(StrEnum):
    """消息角色。"""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ConversationCreate(BaseModel):
    """创建会话。"""

    title: str | None = Field(
        default=None, max_length=255, description="会话标题，缺省为「新会话」"
    )
    description: str | None = Field(default=None, description="会话描述")
    kind: ConversationKind = Field(
        default=ConversationKind.KNOWLEDGE,
        description="会话类型：knowledge（知识问答）/ agent（HR Agent）",
    )
    knowledge_base_ids: list[UUID] = Field(default_factory=list, description="绑定的知识库 ID 列表")

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("description")
    @classmethod
    def _strip_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class ConversationUpdate(BaseModel):
    """局部更新会话；只修改请求中显式出现的字段。"""

    title: str | None = Field(default=None, max_length=255)
    description: str | None = None
    status: ConversationStatus | None = None
    knowledge_base_ids: list[UUID] | None = None

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("会话标题不能为空")
        return stripped

    @field_validator("description")
    @classmethod
    def _strip_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class ConversationRead(BaseModel):
    """会话详情。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="会话 ID")
    title: str = Field(description="会话标题")
    kind: ConversationKind = Field(description="会话类型：knowledge / agent")
    description: str | None = Field(default=None, description="会话描述")
    status: ConversationStatus = Field(description="会话状态")
    knowledge_base_ids: list[UUID] = Field(default_factory=list, description="绑定的知识库 ID 列表")
    total_messages: int = Field(default=0, description="消息总数")
    meta_data: dict[str, Any] | None = Field(default=None, description="扩展元数据")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class ConversationListResponse(BaseModel):
    """会话分页列表。"""

    items: list[ConversationRead] = Field(default_factory=list, description="会话列表")
    total: int = Field(description="总数")
    page: int = Field(description="当前页")
    page_size: int = Field(description="每页数量")


class MessageRead(BaseModel):
    """会话消息详情。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="消息 ID")
    conversation_id: UUID = Field(description="所属会话 ID")
    role: MessageRole = Field(description="消息角色")
    content: str = Field(description="消息文本")
    model_name: str | None = Field(default=None, description="生成该消息的模型名称")
    tokens_used: int | None = Field(default=None, description="生成消耗的 token 数")
    response_time: float | None = Field(default=None, description="回答耗时（秒）")
    context: dict[str, Any] | None = Field(default=None, description="回答上下文")
    meta_data: dict[str, Any] | None = Field(default=None, description="扩展元数据")
    rating: int | None = Field(default=None, description="用户评分 1~5")
    feedback: str | None = Field(default=None, description="用户反馈文本")
    parent_message_id: UUID | None = Field(default=None, description="父消息 ID")
    created_at: datetime = Field(description="创建时间")


class MessageListResponse(BaseModel):
    """会话消息分页列表（按创建时间升序）。"""

    items: list[MessageRead] = Field(default_factory=list, description="消息列表")
    total: int = Field(description="总数")
    page: int = Field(description="当前页")
    page_size: int = Field(description="每页数量")


class MessageFeedback(BaseModel):
    """对助手回答的评分与反馈。"""

    rating: int = Field(ge=1, le=5, description="评分 1~5")
    feedback: str | None = Field(default=None, description="反馈文本")


class ChatRequest(BaseModel):
    """发起一轮知识库问答。"""

    content: str = Field(min_length=1, description="用户问题")

    @field_validator("content")
    @classmethod
    def _strip_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("问题内容不能为空")
        return stripped
