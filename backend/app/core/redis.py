"""异步 Redis 客户端：缓存 / 任务队列（Celery broker 可复用 REDIS_URL）。

连接串来自 settings.redis_url（REDIS_URL），业务代码用 get_redis() 获取
进程内共享的客户端（内置连接池，懒创建、不在导入时连接）；
应用退出时由 lifespan 调用 close_redis() 释放连接池。
"""

from __future__ import annotations

from redis.asyncio import Redis

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_redis: Redis | None = None


def get_redis() -> Redis:
    """返回共享的异步 Redis 客户端；首次调用时按 REDIS_URL 创建。"""
    global _redis
    if _redis is None:
        _redis = Redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            health_check_interval=30,
        )
    return _redis


async def close_redis() -> None:
    """关闭 Redis 连接池：用于应用关闭时释放连接。"""
    global _redis
    if _redis is None:
        return
    try:
        await _redis.aclose()
        logger.info("redis_connection_closed")
    except Exception as e:
        logger.error(f"关闭 Redis 时出错: {e}")
    finally:
        _redis = None
