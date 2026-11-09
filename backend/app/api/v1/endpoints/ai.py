"""AI 助手接口：Dify Chatflow 类型信息、参数、阻塞调用与 SSE 流式调用。

接口层只做鉴权、参数模型与响应组装；Dify 协议、类型校验与错误映射位于
:mod:`app.services.dify_service`。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, DifyClient
from app.schemas.ai import (
    ChatRequest,
    ChatResponse,
    DifyParametersResponse,
    WorkflowTypeRead,
)
from app.schemas.error import ErrorResponse
from app.services import dify_service

router = APIRouter(prefix="/ai", tags=["ai"])

_AUTH_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "缺少令牌、令牌无效或已过期"},
}

_WORKFLOW_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    **_AUTH_ERROR_RESPONSES,
    422: {"model": ErrorResponse, "description": "type / query / inputs 不合法"},
    502: {"model": ErrorResponse, "description": "Dify 鉴权失败、工作流失败或返回异常"},
    503: {"model": ErrorResponse, "description": "Dify 未配置、不可达或超时"},
}


@router.get(
    "/types",
    response_model=list[WorkflowTypeRead],
    summary="列出 Chatflow 类型",
    description=(
        "返回 Dify 开始节点 `type` 1–6 对应的流程说明，以及每个流程必须提供的 "
        "query / inputs，可直接用于前端渲染类型选择与动态表单。"
    ),
    responses=_AUTH_ERROR_RESPONSES,
)
async def list_workflow_types(_current_user: CurrentUser) -> list[WorkflowTypeRead]:
    """返回当前 Chatflow 支持的全部流程类型。"""
    return dify_service.list_workflow_types()


@router.get(
    "/parameters",
    response_model=DifyParametersResponse,
    summary="获取 Dify 应用参数",
    description=(
        "代理 Dify `GET /v1/parameters`，返回开始节点变量定义、开场白、推荐问题与"
        "文件上传限制；也可用于检查 DIFY_API_KEY 是否有效。"
    ),
    responses=_WORKFLOW_ERROR_RESPONSES,
)
async def read_parameters(
    _current_user: CurrentUser,
    client: DifyClient,
) -> DifyParametersResponse:
    """获取 Dify 应用参数。"""
    data = await dify_service.get_parameters(client=client)
    return DifyParametersResponse.model_validate(data)


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="调用 Chatflow（阻塞）",
    description=(
        "按 `type` 执行对应的 HR 流程，等待 Dify 完整生成后一次性返回。"
        "首次调用省略 `conversation_id`，后续传入响应中的值即可延续多轮会话。"
    ),
    responses=_WORKFLOW_ERROR_RESPONSES,
)
async def chat(
    payload: ChatRequest,
    current_user: CurrentUser,
    client: DifyClient,
) -> ChatResponse:
    """阻塞模式调用 Dify Chatflow。"""
    return await dify_service.chat(payload, user_id=current_user.id, client=client)


@router.post(
    "/chat/stream",
    response_class=StreamingResponse,
    response_model=None,
    summary="调用 Chatflow（SSE 流式）",
    description=(
        "与 `/ai/chat` 相同的入参，但以 `text/event-stream` 返回 Dify 原始 SSE 数据块。"
        "每个 `data:` 行都是 JSON，`event` 字段可能是 `workflow_started`、`node_started`、"
        "`message`、`message_end`、`workflow_finished`，流式阶段的错误以 "
        '`{"event":"error","code":...}` 返回。'
    ),
    responses={
        **_WORKFLOW_ERROR_RESPONSES,
        200: {
            "description": "SSE 事件流",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
    },
)
async def chat_stream(
    payload: ChatRequest,
    current_user: CurrentUser,
    client: DifyClient,
) -> StreamingResponse:
    """流式代理 Dify Chatflow；校验失败会在建立流之前返回统一 JSON 错误。"""
    events = dify_service.stream_chat(payload, user_id=current_user.id, client=client)
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
