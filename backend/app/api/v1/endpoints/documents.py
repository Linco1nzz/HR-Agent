"""知识库文档接口：跨知识库列表、详情、原文 / 分块预览、删除与重新处理。

删除知识库只会把文档的 ``knowledge_base_id`` 置空，因此需要一组不依赖知识库
ID 的文档接口来继续管理这些「未关联」文档；``GET /documents?unassigned=true``
就是为此提供的入口。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.db.models import Document
from app.db.session import get_db
from app.schemas.document import (
    DocumentChunkListResponse,
    DocumentContentResponse,
    DocumentListResponse,
    DocumentRead,
    ProcessingStatus,
)
from app.schemas.error import ErrorResponse
from app.services import document_service, knowledge_base_service

router = APIRouter(prefix="/documents", tags=["documents"])

_AUTH_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "缺少令牌、令牌无效或已过期"},
}

_DOCUMENT_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    **_AUTH_ERROR_RESPONSES,
    403: {"model": ErrorResponse, "description": "无权访问或操作该文档"},
    404: {"model": ErrorResponse, "description": "文档不存在"},
}


async def _to_read(db: AsyncSession, record: Document) -> DocumentRead:
    return document_service.to_read(
        record,
        await document_service.knowledge_base_name(db, record),
    )


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="分页查询知识库文档",
    description=(
        "返回可见文档，按上传时间倒序。可用 knowledge_base_id 过滤某个知识库，"
        "或用 unassigned=true 查看知识库已被删除、但文件仍保留的未关联文档。"
    ),
    responses=_DOCUMENT_ERROR_RESPONSES,
)
async def list_documents(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=100, description="每页数量"),
    knowledge_base_id: UUID | None = Query(None, description="所属知识库 ID"),
    unassigned: bool = Query(False, description="只看未关联知识库的文档"),
    keyword: str | None = Query(None, max_length=100, description="文件名 / 正文关键字"),
    processing_status: ProcessingStatus | None = Query(None, description="处理状态"),
) -> DocumentListResponse:
    """分页查询文档。"""
    records, total = await document_service.list_documents(
        db,
        page=page,
        page_size=page_size,
        user=current_user,
        knowledge_base_id=knowledge_base_id,
        unassigned=unassigned,
        keyword=keyword,
        processing_status=processing_status,
    )
    names = await knowledge_base_service.names_by_id(
        db,
        [record.knowledge_base_id for record in records if record.knowledge_base_id],
    )
    return DocumentListResponse(
        items=[
            document_service.to_list_item(
                record,
                names.get(record.knowledge_base_id) if record.knowledge_base_id else None,
            )
            for record in records
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentRead,
    summary="获取文档详情",
    description="返回文件信息、处理状态、分块数量与失败原因。",
    responses=_DOCUMENT_ERROR_RESPONSES,
)
async def get_document(
    document_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> DocumentRead:
    """获取文档详情。"""
    record = await document_service.get_document(db, document_id, user=current_user)
    return await _to_read(db, record)


@router.get(
    "/{document_id}/content",
    response_model=DocumentContentResponse,
    summary="预览文档原文",
    description="返回解析后的完整纯文本，用于原始内容预览。",
    responses=_DOCUMENT_ERROR_RESPONSES,
)
async def get_document_content(
    document_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> DocumentContentResponse:
    """预览解析后的文档原文。"""
    record = await document_service.get_document(db, document_id, user=current_user)
    return document_service.to_content(record)


@router.get(
    "/{document_id}/chunks",
    response_model=DocumentChunkListResponse,
    summary="预览文档分块",
    description="按序号返回切分后的文本块，并标记每块是否已生成向量。",
    responses=_DOCUMENT_ERROR_RESPONSES,
)
async def list_document_chunks(
    document_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> DocumentChunkListResponse:
    """预览文档分块。"""
    items = await document_service.list_chunks(db, document_id, user=current_user)
    return DocumentChunkListResponse(
        document_id=document_id,
        items=items,
        total=len(items),
    )


@router.post(
    "/{document_id}/reprocess",
    response_model=DocumentRead,
    summary="重新处理文档",
    description=(
        "重新解析、切块并向量化（上传者或管理员）。处理失败后修复配置（如 DASHSCOPE_API_KEY）"
        "可调用本接口重试。"
    ),
    responses=_DOCUMENT_ERROR_RESPONSES,
)
async def reprocess_document(
    document_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> DocumentRead:
    """重新处理文档。"""
    record = await document_service.reprocess_document(db, document_id, user=current_user)
    return await _to_read(db, record)


@router.delete(
    "/{document_id}",
    status_code=204,
    response_model=None,
    summary="删除文档",
    description="删除文档记录、向量块与磁盘文件（上传者或管理员）。",
    responses=_DOCUMENT_ERROR_RESPONSES,
)
async def delete_document(
    document_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """删除文档及其文件、向量块。"""
    await document_service.delete_document(db, document_id, user=current_user)
