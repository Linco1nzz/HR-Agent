"""健康检查：存活探针 + 就绪探针。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.db.session import get_db

logger = get_logger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", summary="存活探针")
async def liveness() -> dict[str, str]:
    """进程存活即返回 200，不访问数据库。"""
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.app_env,
        "version": settings.app_version,
    }


@router.get("/ready", summary="就绪探针（检查 PostgreSQL / Redis）")
async def readiness(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """数据库可用时返回 200，否则返回 503。

    Redis 目前仅作缓存 / 队列，不可用时只上报状态，不阻断就绪。
    """
    redis_status = "up"
    try:
        await get_redis().ping()
    except (RedisError, OSError) as exc:
        logger.warning("readiness_redis_check_failed", error=str(exc))
        redis_status = "down"

    try:
        await db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.warning("readiness_check_failed", error=str(exc))
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "database": "down", "redis": redis_status},
        )
    return JSONResponse(
        status_code=200,
        content={"status": "ready", "database": "up", "redis": redis_status},
    )
