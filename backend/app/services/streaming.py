"""Dify Chatflow 流式生成的通用编排。

所有「调用 Chatflow → 增量文本 → 完整结果」的接口共用这里的逻辑：把 Dify 的
原始 SSE 归一化为稳定的业务事件，业务侧只提供请求、结果组装函数与错误文案。

事件协议：

- ``start``：``{"workflow_type"}``，流已建立；
- ``delta``：``{"content"}``，增量文本；
- ``done``：完整结果，字段由 ``build_result`` 决定；
- ``error``：``{"status", "code", "message"}``。

前置校验（参数、资源是否存在、Dify 是否配置）应在调用本模块前完成并直接抛
异常；进入流式响应后，Dify 的 4xx/5xx、超时与断连统一转为 ``error`` 事件。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel

from app.core.exceptions import AppException
from app.core.logging import get_logger
from app.schemas.ai import ChatRequest, ChatUsage
from app.services import dify_service

logger = get_logger(__name__)


@dataclass(slots=True)
class ChatflowResult:
    """流式生成结束后的完整结果，供业务组装 ``done`` 事件。"""

    content: str
    conversation_id: str = ""
    task_id: str = ""
    usage: ChatUsage | None = None


def encode_sse(event: str, data: dict[str, Any]) -> bytes:
    """编码一个标准 SSE 帧（event + 单行 JSON data）。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


async def stream_chatflow(
    request: ChatRequest,
    *,
    user_id: UUID | str,
    client: httpx.AsyncClient,
    workflow_type: str,
    build_result: Callable[[ChatflowResult], BaseModel],
    empty_message: str,
    failure_message: str,
    log_context: dict[str, Any] | None = None,
) -> AsyncIterator[bytes]:
    """执行 Chatflow 并把 Dify SSE 转为业务 SSE 事件。

    Args:
        request: 已校验的 Chatflow 请求。
        user_id: Dify 侧的用户标识。
        client: 复用的异步 HTTP 客户端（由调用方负责生命周期）。
        workflow_type: ``start`` / 日志中的工作流类型。
        build_result: 根据累积结果组装 ``done`` 事件的响应模型。
        empty_message: Dify 未返回任何内容时的错误提示。
        failure_message: 未预期异常时的错误提示。
        log_context: 附加到本次流式日志的结构化字段（如业务主键）。
    """
    fragments: list[str] = []
    conversation_id = ""
    task_id = ""
    usage: ChatUsage | None = None
    fallback_content = ""
    context = {
        "workflow_type": workflow_type,
        "user_id": str(user_id),
        **(log_context or {}),
    }

    yield encode_sse("start", {"workflow_type": workflow_type})

    try:
        async for event in dify_service.iter_stream_events(
            request,
            user_id=user_id,
            client=client,
        ):
            kind = event.get("event")
            if isinstance(event.get("conversation_id"), str):
                conversation_id = event["conversation_id"]
            if isinstance(event.get("task_id"), str):
                task_id = event["task_id"]

            if kind == "message":
                delta = event.get("answer")
                if isinstance(delta, str) and delta:
                    fragments.append(delta)
                    yield encode_sse("delta", {"content": delta})
            elif kind == "message_end":
                metadata = event.get("metadata")
                if isinstance(metadata, dict):
                    raw_usage = metadata.get("usage")
                    if isinstance(raw_usage, dict):
                        usage = ChatUsage.model_validate(raw_usage)
            elif kind == "workflow_finished":
                data = event.get("data")
                if isinstance(data, dict):
                    outputs = data.get("outputs")
                    if isinstance(outputs, dict) and isinstance(outputs.get("answer"), str):
                        fallback_content = outputs["answer"]
            elif kind == "error":
                yield encode_sse(
                    "error",
                    {
                        "status": event.get("status", 502),
                        "code": event.get("code", "DIFY_WORKFLOW_FAILED"),
                        "message": event.get("message", "Dify 工作流执行失败"),
                    },
                )
                return
    except AppException as exc:
        logger.warning(
            "chatflow_stream_failed",
            code=exc.code.value,
            status_code=exc.status_code,
            **context,
        )
        yield encode_sse(
            "error",
            {
                "status": exc.status_code,
                "code": exc.code.value,
                "message": exc.message,
            },
        )
        return
    except Exception:
        logger.exception("chatflow_stream_unexpected_error", **context)
        yield encode_sse(
            "error",
            {
                "status": 500,
                "code": "INTERNAL_ERROR",
                "message": failure_message,
            },
        )
        return

    content = "".join(fragments).strip() or fallback_content.strip()
    if not content:
        yield encode_sse(
            "error",
            {
                "status": 502,
                "code": "DIFY_INVALID_RESPONSE",
                "message": empty_message,
            },
        )
        return

    result = build_result(
        ChatflowResult(
            content=content,
            conversation_id=conversation_id,
            task_id=task_id,
            usage=usage,
        )
    )
    logger.info(
        "chatflow_stream_finished",
        content_chars=len(content),
        conversation_id=conversation_id,
        **context,
    )
    yield encode_sse("done", result.model_dump(mode="json"))
