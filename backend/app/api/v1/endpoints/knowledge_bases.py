"""知识库接口：列表、创建、详情、编辑、删除与知识库内文档上传。

接口层只处理参数校验、调用 service 与组装响应；权限与业务规则位于
:mod:`app.services.knowledge_base_service` 与
:mod:`app.services.document_service`。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.db.session import get_db
from app.schemas.document import (
    DocumentListResponse,
    DocumentRead,
    ProcessingStatus,
)
from app.schemas.error import ErrorResponse
from app.schemas.knowledge_base import (
    KnowledgeBaseCreate,
    KnowledgeBaseListResponse,
    KnowledgeBaseRead,
    KnowledgeBaseUpdate,
)
from app.services import document_service, knowledge_base_service

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])

_AUTH_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "缺少令牌、令牌无效或已过期"},
}

_KB_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    **_AUTH_ERROR_RESPONSES,
    403: {"model": ErrorResponse, "description": "无权访问，或编辑 / 删除需要管理员权限"},
    404: {"model": ErrorResponse, "description": "知识库不存在"},
    409: {"model": ErrorResponse, "description": "知识库名称已存在"},
}

_KB_DOCUMENT_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    **_KB_ERROR_RESPONSES,
    413: {"model": ErrorResponse, "description": "文档超过大小限制"},
    422: {"model": ErrorResponse, "description": "文档格式不支持或内容无法解析"},
}


@router.get(
    "",
    response_model=KnowledgeBaseListResponse,
    summary="分页查询知识库",
    description=(
        "返回可见的知识库，按更新时间倒序；非管理员只能看到公开知识库与自己创建的知识库。"
        "支持名称 / 描述关键字、分类与公开状态筛选。"
    ),
    responses=_KB_ERROR_RESPONSES,
)
async def list_knowledge_bases(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=100, description="每页数量"),
    keyword: str | None = Query(None, max_length=100, description="名称 / 描述关键字"),
    category: str | None = Query(None, max_length=100, description="知识库分类"),
    is_public: bool | None = Query(None, description="是否公开"),
) -> KnowledgeBaseListResponse:
    """分页查询知识库。"""
    records, total = await knowledge_base_service.list_knowledge_bases(
        db,
        page=page,
        page_size=page_size,
        user=current_user,
        keyword=keyword,
        category=category,
        is_public=is_public,
    )
    return KnowledgeBaseListResponse(
        items=[KnowledgeBaseRead.model_validate(record) for record in records],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "",
    response_model=KnowledgeBaseRead,
    status_code=201,
    summary="创建知识库",
    description="任何登录用户都可以创建知识库；名称全局唯一。",
    responses={**_KB_ERROR_RESPONSES, 422: {"model": ErrorResponse, "description": "参数不合法"}},
)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseRead:
    """创建知识库。"""
    record = await knowledge_base_service.create_knowledge_base(db, payload, user=current_user)
    return KnowledgeBaseRead.model_validate(record)


@router.get(
    "/{kb_id}",
    response_model=KnowledgeBaseRead,
    summary="获取知识库详情",
    description="返回基本信息、配置、标签与文档数量。",
    responses=_KB_ERROR_RESPONSES,
)
async def get_knowledge_base(
    kb_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseRead:
    """获取知识库详情。"""
    record = await knowledge_base_service.get_knowledge_base(db, kb_id, user=current_user)
    return KnowledgeBaseRead.model_validate(record)


@router.patch(
    "/{kb_id}",
    response_model=KnowledgeBaseRead,
    summary="编辑知识库（管理员）",
    description="局部更新知识库；只修改请求中显式传入的字段。",
    responses=_KB_ERROR_RESPONSES,
)
async def update_knowledge_base(
    kb_id: UUID,
    payload: KnowledgeBaseUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseRead:
    """编辑知识库。"""
    record = await knowledge_base_service.update_knowledge_base(
        db,
        kb_id,
        payload,
        user=current_user,
    )
    return KnowledgeBaseRead.model_validate(record)


@router.delete(
    "/{kb_id}",
    status_code=204,
    response_model=None,
    summary="删除知识库（管理员）",
    description=(
        "删除知识库记录，但不删除文档文件与向量块：关联文档的 knowledge_base_id "
        "会被置空，之后可以在文档列表的「未关联」中继续管理。"
    ),
    responses=_KB_ERROR_RESPONSES,
)
async def delete_knowledge_base(
    kb_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """删除知识库（文档仅解除关联）。"""
    await knowledge_base_service.delete_knowledge_base(db, kb_id, user=current_user)


@router.get(
    "/{kb_id}/documents",
    response_model=DocumentListResponse,
    summary="查询知识库下的文档",
    description="分页返回知识库下的文档，按上传时间倒序；支持文件名 / 正文关键字与状态筛选。",
    responses=_KB_ERROR_RESPONSES,
)
async def list_knowledge_base_documents(
    kb_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=100, description="每页数量"),
    keyword: str | None = Query(None, max_length=100, description="文件名 / 正文关键字"),
    processing_status: ProcessingStatus | None = Query(None, description="处理状态"),
) -> DocumentListResponse:
    """分页查询知识库下的文档。"""
    knowledge_base = await knowledge_base_service.get_knowledge_base(
        db,
        kb_id,
        user=current_user,
    )
    records, total = await document_service.list_documents(
        db,
        page=page,
        page_size=page_size,
        user=current_user,
        knowledge_base_id=knowledge_base.id,
        keyword=keyword,
        processing_status=processing_status,
    )
    return DocumentListResponse(
        items=[document_service.to_list_item(record, knowledge_base.name) for record in records],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/{kb_id}/documents",
    response_model=DocumentRead,
    status_code=201,
    summary="上传文档到知识库",
    description=(
        "上传 PDF / DOC / DOCX / TXT / MD / CSV 文档。保存后立即用临时文件提取正文，"
        "经 LLM 语义分割点 + LangChain 切分后向量化入库。处理失败时文档仍会保留，"
        "返回 processing_status=failed 与失败原因，可调用重新处理接口重试。"
    ),
    responses=_KB_DOCUMENT_ERROR_RESPONSES,
)
async def upload_knowledge_base_document(
    kb_id: UUID,
    current_user: CurrentUser,
    file: UploadFile = File(..., description="知识库文档"),
    db: AsyncSession = Depends(get_db),
) -> DocumentRead:
    """上传并处理文档。"""
    content = await file.read()
    record = await document_service.upload_document(
        db,
        knowledge_base_id=kb_id,
        filename=file.filename or "",
        content=content,
        mime_type=file.content_type,
        user=current_user,
    )
    return document_service.to_read(record, await document_service.knowledge_base_name(db, record))
