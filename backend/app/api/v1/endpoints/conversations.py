"""问答会话接口：会话 CRUD、消息分页、回答反馈与 SSE 流式问答。

接口层只处理参数校验、调用 service 与组装响应；业务逻辑位于
:mod:`app.services.conversation_service` 与 :mod:`app.services.qa_service`。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.db.session import get_db
from app.schemas.conversation import (
    ChatRequest,
    ConversationCreate,
    ConversationListResponse,
    ConversationRead,
    ConversationUpdate,
    MessageFeedback,
    MessageListResponse,
    MessageRead,
)
from app.schemas.error import ErrorResponse
from app.services import conversation_service, qa_service
from app.services.streaming import encode_sse

router = APIRouter(prefix="/conversations", tags=["conversations"])

_AUTH_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "缺少令牌、令牌无效或已过期"},
}

_CONVERSATION_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    **_AUTH_ERROR_RESPONSES,
    403: {"model": ErrorResponse, "description": "绑定的知识库无权访问"},
    404: {"model": ErrorResponse, "description": "会话或消息不存在"},
}


@router.post(
    "",
    response_model=ConversationRead,
    status_code=201,
    summary="创建会话",
    description="创建问答会话，可绑定当前用户可见的知识库；标题缺省为「新会话」。",
    responses={
        **_CONVERSATION_ERROR_RESPONSES,
        422: {"model": ErrorResponse, "description": "参数不合法"},
    },
)
async def create_conversation(
    payload: ConversationCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ConversationRead:
    """创建会话。"""
    record = await conversation_service.create_conversation(db, payload, user=current_user)
    return ConversationRead.model_validate(record)


@router.get(
    "",
    response_model=ConversationListResponse,
    summary="分页查询会话",
    description="返回当前用户的会话，按更新时间倒序。",
    responses=_AUTH_ERROR_RESPONSES,
)
async def list_conversations(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=100, description="每页数量"),
) -> ConversationListResponse:
    """分页查询会话。"""
    records, total = await conversation_service.list_conversations(
        db,
        page=page,
        page_size=page_size,
        user=current_user,
    )
    return ConversationListResponse(
        items=[ConversationRead.model_validate(record) for record in records],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{conversation_id}",
    response_model=ConversationRead,
    summary="获取会话详情",
    description="返回会话基本信息与绑定的知识库；仅创建者可见。",
    responses=_CONVERSATION_ERROR_RESPONSES,
)
async def get_conversation(
    conversation_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ConversationRead:
    """获取会话详情。"""
    record = await conversation_service.get_conversation(db, conversation_id, user=current_user)
    return ConversationRead.model_validate(record)


@router.patch(
    "/{conversation_id}",
    response_model=ConversationRead,
    summary="编辑会话",
    description="局部更新标题、描述、状态与绑定的知识库；只修改显式传入的字段。",
    responses=_CONVERSATION_ERROR_RESPONSES,
)
async def update_conversation(
    conversation_id: UUID,
    payload: ConversationUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ConversationRead:
    """编辑会话。"""
    record = await conversation_service.update_conversation(
        db,
        conversation_id,
        payload,
        user=current_user,
    )
    return ConversationRead.model_validate(record)


@router.delete(
    "/{conversation_id}",
    status_code=204,
    response_model=None,
    summary="删除会话",
    description="删除会话及其全部消息。",
    responses=_CONVERSATION_ERROR_RESPONSES,
)
async def delete_conversation(
    conversation_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """删除会话（级联删除消息）。"""
    await conversation_service.delete_conversation(db, conversation_id, user=current_user)


@router.get(
    "/{conversation_id}/messages",
    response_model=MessageListResponse,
    summary="分页查询会话消息",
    description="按创建时间升序返回会话消息。",
    responses=_CONVERSATION_ERROR_RESPONSES,
)
async def list_messages(
    conversation_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=100, description="每页数量"),
) -> MessageListResponse:
    """分页查询会话消息。"""
    records, total = await conversation_service.list_messages(
        db,
        conversation_id,
        page=page,
        page_size=page_size,
        user=current_user,
    )
    return MessageListResponse(
        items=[MessageRead.model_validate(record) for record in records],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.patch(
    "/{conversation_id}/messages/{message_id}/feedback",
    response_model=MessageRead,
    summary="评价消息",
    description="对会话中的消息提交 1~5 分评分与可选反馈。",
    responses=_CONVERSATION_ERROR_RESPONSES,
)
async def update_message_feedback(
    conversation_id: UUID,
    message_id: UUID,
    payload: MessageFeedback,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MessageRead:
    """评价消息。"""
    record = await conversation_service.update_message_feedback(
        db,
        conversation_id,
        message_id,
        payload,
        user=current_user,
    )
    return MessageRead.model_validate(record)


@router.post(
    "/{conversation_id}/chat",
    summary="知识库问答（SSE 流式）",
    description=(
        "发起一轮问答。事件序列：meta → (sources) → delta* → done | error；"
        "每个事件格式为 event: {name} + data: {json}。会话绑定的知识库决定检索范围。"
    ),
    response_class=StreamingResponse,
    responses=_CONVERSATION_ERROR_RESPONSES,
)
async def chat(
    conversation_id: UUID,
    payload: ChatRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """SSE 流式问答。"""
    # 前置归属校验：不存在 / 非本人会话直接返回 404，而不是 SSE error
    await conversation_service.get_conversation(db, conversation_id, user=current_user)

    async def event_stream() -> AsyncIterator[bytes]:
        async for event, data in qa_service.chat(
            conversation_id, payload.content, user=current_user
        ):
            yield encode_sse(event, data)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
