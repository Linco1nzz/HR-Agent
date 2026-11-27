"""Redis 接入测试：单测不发起网络连接；集成用例需 Docker 中的 Redis。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from app.core.redis import close_redis, get_redis


@pytest.fixture(autouse=True)
async def _fresh_redis() -> AsyncIterator[None]:
    """pytest-asyncio 每个用例独立事件循环，前后释放客户端避免跨循环复用连接。"""
    await close_redis()
    yield
    await close_redis()


def test_get_redis_returns_shared_client() -> None:
    """懒创建且进程内共享同一客户端（创建时不连接外部服务）。"""
    assert get_redis() is get_redis()


@pytest.mark.integration
async def test_redis_ping() -> None:
    """需要 Docker 中的 Redis（uv run pytest --run-integration）。"""
    assert await get_redis().ping() is True


@pytest.mark.integration
async def test_redis_set_get_roundtrip() -> None:
    """写入 / 读取 / 删除一条临时键，验证鉴权与编解码配置。"""
    redis = get_redis()
    key = "hr_agent:test:redis_roundtrip"
    try:
        await redis.set(key, "你好，Redis", ex=30)
        assert await redis.get(key) == "你好，Redis"
    finally:
        await redis.delete(key)


@pytest.mark.integration
async def test_close_redis_allows_recreate() -> None:
    """close_redis 释放后可重新创建客户端并继续访问。"""
    assert await get_redis().ping() is True
    await close_redis()
    assert await get_redis().ping() is True
