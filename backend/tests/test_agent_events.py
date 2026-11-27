"""任务事件单元测试：Redis 发布与 SSE 帧编码（不依赖真实 Redis）。"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from app.services.agent import events


class FakeRedis:
    """只实现 publish 的 Redis 替身。"""

    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, payload: str) -> int:
        self.published.append((channel, payload))
        return 1


class FailingRedis:
    """模拟 Redis 不可用。"""

    async def publish(self, channel: str, payload: str) -> int:  # noqa: ARG002
        raise ConnectionError("redis down")


async def test_publish_event_uses_task_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    """事件发布到 ``task_channel:{task_id}``，负载可被前端解码。"""
    fake = FakeRedis()
    monkeypatch.setattr(events, "get_redis", lambda: fake)
    task_id = uuid4()

    await events.publish_event(task_id, "step", {"step": {"tool": "generate_jd"}})

    assert len(fake.published) == 1
    channel, payload = fake.published[0]
    assert channel == f"task_channel:{task_id}"
    decoded = events.decode_event(payload)
    assert decoded is not None
    event, data = decoded
    assert event == "step"
    assert data["step"]["tool"] == "generate_jd"


async def test_publish_event_swallows_redis_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redis 故障时只记日志，不影响 Worker 执行。"""
    monkeypatch.setattr(events, "get_redis", lambda: FailingRedis())
    await events.publish_event(uuid4(), "task_end", {"status": "completed"})


def test_decode_event_rejects_invalid_payload() -> None:
    """非法负载返回 None，不会让 SSE 连接崩溃。"""
    assert events.decode_event("not-json") is None
    assert events.decode_event(json.dumps({"event": "step"})) is None
    assert events.decode_event(json.dumps({"event": 1, "data": {}})) is None


def test_encode_event_uses_named_event() -> None:
    """编码结果带 ``event:`` 行，前端按命名事件分发。"""
    frame = events.encode_event("confirm_required", {"summary": "即将保存 JD"})
    assert b"event: confirm_required" in frame
    assert b"data: " in frame
    assert frame.endswith(b"\n\n")
