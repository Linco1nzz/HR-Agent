"""任务事件推送：Redis pub/sub 中转 + SSE 帧编码。

Worker 先把状态落库、再 publish；SSE 接口建连时先推数据库快照，再订阅同一个
channel，因此刷新 / 重连不会丢已发生的进度（ADR 0003 / 0008）。
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.core.logging import get_logger
from app.core.redis import get_redis
from app.services.streaming import encode_sse

logger = get_logger(__name__)

#: Redis 频道前缀：``task_channel:{task_id}``
CHANNEL_PREFIX = "task_channel:"

#: SSE 心跳帧：避免反向代理在长时间无事件时断开
KEEPALIVE_FRAME = b": keep-alive\n\n"


def task_channel(task_id: UUID | str) -> str:
    """返回任务事件频道名。"""
    return f"{CHANNEL_PREFIX}{task_id}"


async def publish_event(task_id: UUID | str, event: str, data: dict[str, Any]) -> None:
    """把任务事件发布到 Redis。

    Redis 不可用时只记录日志、不打断 Worker：任务状态仍以数据库为准，前端重连
    后能通过快照追平。
    """
    payload = json.dumps({"event": event, "data": data}, ensure_ascii=False, default=str)
    try:
        await get_redis().publish(task_channel(task_id), payload)
    except Exception as exc:  # pragma: no cover - 依赖外部 Redis
        logger.warning(
            "agent_event_publish_failed",
            task_id=str(task_id),
            event_name=event,
            error=str(exc),
        )


def decode_event(raw: str | bytes) -> tuple[str, dict[str, Any]] | None:
    """解析 pub/sub 消息；非法负载返回 None。"""
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("agent_event_decode_failed", raw=str(raw)[:200])
        return None
    if not isinstance(payload, dict):
        return None
    event = payload.get("event")
    data = payload.get("data")
    if not isinstance(event, str) or not isinstance(data, dict):
        return None
    return event, data


def encode_event(event: str, data: dict[str, Any]) -> bytes:
    """把业务事件编码成 SSE 帧。"""
    return encode_sse(event, data)
