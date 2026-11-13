"""知识库文档相关的请求 / 响应模型。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProcessingStatus(StrEnum):
    """文档处理状态。"""

    UPLOADED = "uploaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class DocumentListItem(BaseModel):
    """文档列表项（不返回正文与分块，减少列表响应体）。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="文档 ID")
    knowledge_base_id: UUID | None = Field(default=None, description="所属知识库 ID")
    knowledge_base_name: str | None = Field(default=None, description="所属知识库名称")
    original_filename: str = Field(description="原始文件名")
    mime_type: str = Field(description="文件 MIME 类型")
    file_size: int = Field(description="文件大小（字节）")
    processing_status: ProcessingStatus = Field(description="处理状态")
    processing_error: str | None = Field(default=None, description="处理失败原因")
    chunk_count: int = Field(default=0, description="有效分块数量")
    category: str | None = Field(default=None, description="文档分类")
    tags: list[str] | None = Field(default=None, description="标签列表")
    processed_at: datetime | None = Field(default=None, description="处理完成时间")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class DocumentRead(DocumentListItem):
    """文档详情（含文件哈希与扩展元数据，不含正文）。"""

    filename: str = Field(description="存储文件名")
    file_hash: str = Field(description="文件 SHA256 哈希值")
    meta_data: dict[str, Any] | None = Field(default=None, description="扩展元数据")
    user_id: UUID = Field(description="上传用户 ID")
    created_by: UUID | None = Field(default=None, description="创建人 ID")


class DocumentListResponse(BaseModel):
    """文档分页列表。"""

    items: list[DocumentListItem] = Field(default_factory=list, description="文档列表")
    total: int = Field(description="总数")
    page: int = Field(description="当前页")
    page_size: int = Field(description="每页数量")


class DocumentContentResponse(BaseModel):
    """文档原始文本预览。"""

    document_id: UUID = Field(description="文档 ID")
    original_filename: str = Field(description="原始文件名")
    mime_type: str = Field(description="文件 MIME 类型")
    content: str = Field(description="解析后的完整文本")
    char_count: int = Field(description="文本字符数")
    chunk_count: int = Field(description="有效分块数量")
    processing_status: ProcessingStatus = Field(description="处理状态")


class DocumentChunkItem(BaseModel):
    """单个分块（不返回向量，只标记是否已向量化）。"""

    id: str = Field(description="分块 ID（langchain_pg_embedding 主键）")
    chunk_index: int = Field(description="分块序号，从 0 开始")
    content: str = Field(description="分块文本")
    char_count: int = Field(description="分块字符数")
    has_embedding: bool = Field(description="是否已生成向量")
    meta_data: dict[str, Any] | None = Field(default=None, description="分块扩展元数据")


class DocumentChunkListResponse(BaseModel):
    """文档分块预览。"""

    document_id: UUID = Field(description="文档 ID")
    items: list[DocumentChunkItem] = Field(default_factory=list, description="分块列表")
    total: int = Field(description="分块总数")
