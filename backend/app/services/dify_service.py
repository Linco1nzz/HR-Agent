"""Dify Chatflow 调用服务。

当前 Dify 应用 ``hr_agent`` 属于 **advanced-chat（Chatflow）** 模式，对应接口是
``POST /v1/chat-messages``（阻塞 / SSE），而不是 Workflow 应用的
``POST /v1/workflows/run``。Chatflow 的“按 type 分支”由 Dify 开始节点的数字变量
``type`` 完成，本服务负责：

1. 校验 ``type`` 与各流程必需的 ``query`` / ``inputs``；
2. 组装 Dify 请求（``inputs.type`` 由顶层字段覆盖）；
3. 把 Dify 的 400/401/429/5xx、超时与非法响应转换为项目统一异常；
4. 原样透传 SSE 数据块，流式场景下的错误以 ``event: error`` 事件返回。
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

from app.core.config import settings
from app.core.exceptions import (
    AppException,
    DifyInvalidParamError,
    DifyInvalidResponseError,
    DifyNotConfiguredError,
    DifyUnauthorizedError,
    DifyUnavailableError,
    DifyWorkflowFailedError,
    RateLimitError,
    WorkflowValidationError,
)
from app.core.logging import get_logger
from app.schemas.ai import (
    ChatRequest,
    ChatResponse,
    ChatUsage,
    WorkflowType,
    WorkflowTypeRead,
)

logger = get_logger(__name__)

_CHAT_PATH = "chat-messages"
_PARAMETERS_PATH = "parameters"


@dataclass(frozen=True, slots=True)
class WorkflowTypeSpec:
    """一个 ``type`` 分支的调用契约。"""

    type: WorkflowType
    key: str
    name: str
    description: str
    query_required: bool
    query_hint: str
    required_inputs: tuple[str, ...] = ()
    #: query 可省略但 Dify 又要求非空时，由后端补一个默认值
    default_query: str | None = None


#: 与 Dify 当前 Chatflow 的 if-else 分支保持一致；修改 Dify 流程时同步更新。
WORKFLOW_TYPE_SPECS: dict[WorkflowType, WorkflowTypeSpec] = {
    WorkflowType.JD_GENERATION: WorkflowTypeSpec(
        type=WorkflowType.JD_GENERATION,
        key="jd_generation",
        name="JD 生成",
        description="根据岗位需求生成职位描述（JD）",
        query_required=True,
        query_hint="岗位需求 / 招聘要求",
    ),
    WorkflowType.RESUME_CRITERIA: WorkflowTypeSpec(
        type=WorkflowType.RESUME_CRITERIA,
        key="resume_criteria",
        name="简历评价标准",
        description="根据 JD 生成 100 分制、至少 4 个维度的简历评价标准",
        query_required=True,
        query_hint="JD 内容",
    ),
    WorkflowType.RESUME_EVALUATION: WorkflowTypeSpec(
        type=WorkflowType.RESUME_EVALUATION,
        key="resume_evaluation",
        name="简历评价",
        description="按评价标准对简历逐项打分，并提取候选人基础信息",
        query_required=True,
        query_hint="简历评价标准（通常来自 type=2 的输出）",
        required_inputs=("jianli",),
    ),
    WorkflowType.INTERVIEW_PLAN: WorkflowTypeSpec(
        type=WorkflowType.INTERVIEW_PLAN,
        key="interview_plan",
        name="面试方案",
        description="根据 JD 与简历生成面试方案及不少于 15 道面试题",
        query_required=False,
        query_hint="可选补充说明",
        required_inputs=("jd", "jianli"),
        # Dify /chat-messages 要求 query 非空，但该分支只使用 jd / jianli
        default_query="请根据 JD 和简历生成面试方案与面试题",
    ),
    WorkflowType.EXAM_GENERATION: WorkflowTypeSpec(
        type=WorkflowType.EXAM_GENERATION,
        key="exam_generation",
        name="试卷生成",
        description="根据文档内容与试卷要求生成单选题、多选题、判断题和简答题",
        query_required=True,
        query_hint="试卷要求（题型、数量、分值等）",
        required_inputs=("fileContent",),
    ),
    WorkflowType.EXAM_GRADING: WorkflowTypeSpec(
        type=WorkflowType.EXAM_GRADING,
        key="exam_grading",
        name="阅卷评分",
        description="根据标准答案对用户试卷逐题打分，返回逗号分隔的分数",
        query_required=True,
        query_hint="用户试卷内容（JSON 数组，包含题目、答案、分值等）",
    ),
}

#: 与 Dify 开始节点 max_length 对齐的输入长度限制
_INPUT_MAX_LENGTHS: dict[str, int] = {
    "jd": 48_000,
    "jianli": 80_000,
    "jobName": 48,
    "jobResponsibilities": 1_000,
    "fileContent": 50_000,
    "evaluationModel": 5_000,
}

#: 进程内复用的 HTTP 客户端（由 lifespan 关闭）
_client: httpx.AsyncClient | None = None


# ---------------------------------------------------------------------------
# 类型信息与入参校验
# ---------------------------------------------------------------------------
def list_workflow_types() -> list[WorkflowTypeRead]:
    """返回全部流程类型说明，顺序与 Dify 的 type 1–6 一致。"""
    return [
        WorkflowTypeRead(
            type=spec.type,
            key=spec.key,
            name=spec.name,
            description=spec.description,
            query_required=spec.query_required,
            query_hint=spec.query_hint,
            required_inputs=list(spec.required_inputs),
        )
        for spec in WORKFLOW_TYPE_SPECS.values()
    ]


def _has_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_chat_request(payload: ChatRequest) -> None:
    """校验当前 type 所需的 query 与 inputs，失败抛 422 业务异常。"""
    spec = WORKFLOW_TYPE_SPECS[payload.type]

    if spec.query_required and not payload.query.strip():
        raise WorkflowValidationError(
            f"type={int(payload.type)}（{spec.name}）需要提供 query：{spec.query_hint}",
            details={
                "type": int(payload.type),
                "field": "query",
                "hint": spec.query_hint,
            },
        )

    missing = [name for name in spec.required_inputs if not _has_text(payload.inputs.get(name))]
    if missing:
        raise WorkflowValidationError(
            f"type={int(payload.type)}（{spec.name}）缺少必填输入：{', '.join(missing)}",
            details={
                "type": int(payload.type),
                "missing_inputs": missing,
            },
        )

    for name, max_length in _INPUT_MAX_LENGTHS.items():
        value = payload.inputs.get(name)
        if isinstance(value, str) and len(value) > max_length:
            raise WorkflowValidationError(
                f"输入 {name} 超过最大长度 {max_length}",
                details={
                    "type": int(payload.type),
                    "field": f"inputs.{name}",
                    "max_length": max_length,
                },
            )


# ---------------------------------------------------------------------------
# HTTP 客户端
# ---------------------------------------------------------------------------
def _api_url(path: str) -> str:
    """拼接 Dify API 地址；``DIFY_BASE_URL`` 需包含 ``/v1``。"""
    return f"{settings.dify_base_url.rstrip('/')}/{path.lstrip('/')}"


def get_client() -> httpx.AsyncClient:
    """返回进程内共享的 Dify HTTP 客户端（首次调用时创建）。

    同时作为 FastAPI 依赖使用，便于测试中通过 ``dependency_overrides`` 替换。
    """
    global _client
    if _client is None:
        if not settings.dify_api_key:
            raise DifyNotConfiguredError()
        _client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {settings.dify_api_key}"},
            timeout=httpx.Timeout(
                settings.dify_timeout_seconds,
                connect=settings.dify_connect_timeout_seconds,
            ),
        )
        logger.info(
            "dify_client_created",
            base_url=settings.dify_base_url,
            timeout_seconds=settings.dify_timeout_seconds,
        )
    return _client


async def close_client() -> None:
    """关闭共享客户端；由应用 lifespan 在退出时调用。"""
    global _client
    client, _client = _client, None
    if client is not None:
        await client.aclose()
        logger.info("dify_client_closed")


# ---------------------------------------------------------------------------
# 请求组装与响应解析
# ---------------------------------------------------------------------------
def build_chat_payload(
    payload: ChatRequest,
    *,
    user_id: UUID | str,
    response_mode: str,
) -> dict[str, object]:
    """把业务请求转换为 Dify ``/chat-messages`` 的请求体。"""
    inputs = {key: value for key, value in payload.inputs.items() if value is not None}
    # 顶层 type 是唯一事实来源，避免 inputs 中传入不一致的值
    inputs["type"] = int(payload.type)

    spec = WORKFLOW_TYPE_SPECS[payload.type]
    query = payload.query or spec.default_query or payload.query

    body: dict[str, object] = {
        "query": query,
        "inputs": inputs,
        "response_mode": response_mode,
        "user": str(user_id),
        "auto_generate_name": payload.auto_generate_name,
    }
    if payload.conversation_id:
        body["conversation_id"] = payload.conversation_id
    if payload.files:
        body["files"] = payload.files
    return body


def _parse_json(response: httpx.Response) -> dict[str, object]:
    try:
        data = response.json()
    except ValueError as exc:
        raise DifyInvalidResponseError(
            "Dify 返回了非 JSON 响应",
            details={"status_code": response.status_code},
        ) from exc
    if not isinstance(data, dict):
        raise DifyInvalidResponseError(
            "Dify 返回的数据不是 JSON 对象",
            details={"status_code": response.status_code},
        )
    return data


def _dify_error_details(response: httpx.Response) -> dict[str, object]:
    """提取 Dify 错误体的 code / message，供统一错误响应与日志使用。"""
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    return {
        "status_code": response.status_code,
        "dify_code": body.get("code"),
        "dify_message": body.get("message"),
    }


def _raise_for_dify_error(response: httpx.Response) -> None:
    """把 Dify 的 HTTP 错误映射为项目异常。"""
    details = _dify_error_details(response)
    dify_message = details.get("dify_message")
    message = dify_message if isinstance(dify_message, str) and dify_message else None

    if response.status_code in (401, 403):
        raise DifyUnauthorizedError(
            "Dify 应用鉴权失败，请检查 DIFY_API_KEY",
            details=details,
        )
    if response.status_code == 400:
        raise DifyInvalidParamError(message or "Dify 判定请求参数不合法", details=details)
    if response.status_code == 404:
        raise DifyWorkflowFailedError(
            "Dify 应用或接口不存在，请检查 DIFY_BASE_URL 与应用状态",
            details=details,
        )
    if response.status_code == 429:
        raise RateLimitError("Dify 请求过于频繁，请稍后重试", details=details)
    if response.status_code >= 500:
        raise DifyUnavailableError(message or "Dify 服务暂时不可用", details=details)
    raise DifyWorkflowFailedError(message or "Dify 工作流执行失败", details=details)


def _to_chat_response(data: dict[str, object], workflow_type: WorkflowType) -> ChatResponse:
    if data.get("event") == "error" or data.get("code"):
        raise DifyWorkflowFailedError(
            str(data.get("message") or "Dify 工作流执行失败"),
            details={"event": data.get("event"), "dify_code": data.get("code")},
        )

    answer = data.get("answer")
    if not isinstance(answer, str):
        raise DifyInvalidResponseError(
            "Dify 响应缺少 answer 字段",
            details={"event": data.get("event"), "keys": sorted(data)},
        )

    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    usage: ChatUsage | None = None
    raw_usage = metadata.get("usage")
    if isinstance(raw_usage, dict):
        usage = ChatUsage.model_validate(raw_usage)

    resources = metadata.get("retriever_resources")
    retriever_resources = resources if isinstance(resources, list) else []

    return ChatResponse(
        event=str(data.get("event") or "message"),
        type=workflow_type,
        task_id=str(data.get("task_id") or ""),
        message_id=str(data.get("message_id") or ""),
        conversation_id=str(data.get("conversation_id") or ""),
        answer=answer,
        mode=data.get("mode") if isinstance(data.get("mode"), str) else None,
        created_at=data.get("created_at") if isinstance(data.get("created_at"), int) else None,
        usage=usage,
        retriever_resources=retriever_resources,
        metadata=metadata,
    )


def _sse_error(exc: AppException) -> bytes:
    """把流式阶段无法再改 HTTP 状态码的错误编码为 SSE error 事件。"""
    payload: dict[str, Any] = {
        "event": "error",
        "status": exc.status_code,
        "code": exc.code.value,
        "message": exc.message,
    }
    if exc.details:
        payload["details"] = exc.details
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


# ---------------------------------------------------------------------------
# 对外调用
# ---------------------------------------------------------------------------
async def chat(
    payload: ChatRequest,
    *,
    user_id: UUID | str,
    client: httpx.AsyncClient | None = None,
) -> ChatResponse:
    """阻塞模式调用 Chatflow，返回归一化后的回答。"""
    validate_chat_request(payload)
    http = client or get_client()
    body = build_chat_payload(payload, user_id=user_id, response_mode="blocking")

    logger.info(
        "dify_chat_started",
        type=int(payload.type),
        user_id=str(user_id),
        conversation_id=payload.conversation_id,
    )
    started = time.perf_counter()

    try:
        response = await http.post(
            _api_url(_CHAT_PATH),
            json=body,
            headers={"Accept": "application/json"},
        )
    except httpx.TimeoutException as exc:
        logger.warning("dify_chat_timeout", type=int(payload.type))
        raise DifyUnavailableError("Dify 响应超时，请稍后重试") from exc
    except httpx.HTTPError as exc:
        logger.warning("dify_chat_unreachable", type=int(payload.type), error=str(exc))
        raise DifyUnavailableError("无法连接 Dify 服务，请检查服务是否已启动") from exc

    if not response.is_success:
        logger.warning(
            "dify_chat_rejected",
            type=int(payload.type),
            status_code=response.status_code,
        )
        _raise_for_dify_error(response)

    result = _to_chat_response(_parse_json(response), payload.type)
    logger.info(
        "dify_chat_finished",
        type=int(payload.type),
        elapsed_ms=round((time.perf_counter() - started) * 1000),
        answer_chars=len(result.answer),
        conversation_id=result.conversation_id,
    )
    return result


def stream_chat(
    payload: ChatRequest,
    *,
    user_id: UUID | str,
    client: httpx.AsyncClient | None = None,
) -> AsyncIterator[bytes]:
    """流式模式调用 Chatflow。

    校验、客户端创建等前置错误会在返回生成器之前抛出；一旦进入流式响应，
    Dify 的 4xx/5xx、超时或断连都编码为 ``event: error`` 的 SSE 事件，避免在
    响应头已发送后无法再返回 JSON 错误。
    """
    validate_chat_request(payload)
    http = client or get_client()
    body = build_chat_payload(payload, user_id=user_id, response_mode="streaming")
    return _stream_chat_events(http, body, payload)


async def _stream_chat_events(
    http: httpx.AsyncClient,
    body: dict[str, object],
    payload: ChatRequest,
) -> AsyncIterator[bytes]:
    logger.info(
        "dify_stream_started",
        type=int(payload.type),
        conversation_id=payload.conversation_id,
    )
    started = time.perf_counter()
    chunks = 0

    try:
        async with http.stream(
            "POST",
            _api_url(_CHAT_PATH),
            json=body,
            headers={"Accept": "text/event-stream"},
        ) as response:
            if not response.is_success:
                await response.aread()
                logger.warning(
                    "dify_stream_rejected",
                    type=int(payload.type),
                    status_code=response.status_code,
                )
                try:
                    _raise_for_dify_error(response)
                except AppException as exc:
                    yield _sse_error(exc)
                return

            async for chunk in response.aiter_bytes():
                if chunk:
                    chunks += 1
                    yield chunk
    except httpx.TimeoutException:
        logger.warning("dify_stream_timeout", type=int(payload.type))
        yield _sse_error(DifyUnavailableError("Dify 响应超时，请稍后重试"))
    except httpx.HTTPError as exc:
        logger.warning("dify_stream_unreachable", type=int(payload.type), error=str(exc))
        yield _sse_error(DifyUnavailableError("Dify 流式连接中断，请稍后重试"))
    finally:
        logger.info(
            "dify_stream_finished",
            type=int(payload.type),
            elapsed_ms=round((time.perf_counter() - started) * 1000),
            chunks=chunks,
        )


async def iter_stream_events(
    payload: ChatRequest,
    *,
    user_id: UUID | str,
    client: httpx.AsyncClient | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """把 Dify SSE 解析成 JSON 事件字典（供需要重组的业务使用）。

    ``event: ping``、注释行等没有 ``data`` 的控制帧会被忽略；每个 ``data:``
    行按 SSE 规范可多行拼接，再按 JSON 解析。解析失败的帧只记录日志并跳过，
    不影响后续 token。
    """
    stream = stream_chat(payload, user_id=user_id, client=client)
    async for event in _iter_sse_json(stream):
        yield event


async def _iter_sse_json(chunks: AsyncIterator[bytes]) -> AsyncIterator[dict[str, Any]]:
    buffer = b""
    async for chunk in chunks:
        if not chunk:
            continue
        buffer += chunk
        # SSE 允许 CRLF；统一后再按空行分帧，避免 \r\n\r\n 漏切
        buffer = buffer.replace(b"\r\n", b"\n")
        while True:
            boundary = buffer.find(b"\n\n")
            if boundary < 0:
                break
            frame, buffer = buffer[:boundary], buffer[boundary + 2 :]
            event = _parse_sse_frame(frame)
            if event is not None:
                yield event

    if buffer.strip():
        event = _parse_sse_frame(buffer)
        if event is not None:
            yield event


def _parse_sse_frame(frame: bytes) -> dict[str, Any] | None:
    """解析单个 SSE 帧；没有 data 或不是 JSON 对象时返回 None。"""
    data_lines = [line[5:].lstrip(b" ") for line in frame.split(b"\n") if line.startswith(b"data:")]
    if not data_lines:
        return None

    try:
        data = json.loads(b"\n".join(data_lines).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        logger.warning("dify_stream_invalid_frame", frame_size=len(frame))
        return None
    return data if isinstance(data, dict) else None


async def get_parameters(client: httpx.AsyncClient | None = None) -> dict[str, object]:
    """获取 Dify 应用参数（输入表单、开场白、文件限制等）。"""
    http = client or get_client()
    try:
        response = await http.get(
            _api_url(_PARAMETERS_PATH),
            headers={"Accept": "application/json"},
        )
    except httpx.TimeoutException as exc:
        raise DifyUnavailableError("获取 Dify 应用参数超时") from exc
    except httpx.HTTPError as exc:
        raise DifyUnavailableError("无法连接 Dify 服务，请检查服务是否已启动") from exc

    if not response.is_success:
        logger.warning("dify_parameters_rejected", status_code=response.status_code)
        _raise_for_dify_error(response)

    return _parse_json(response)
