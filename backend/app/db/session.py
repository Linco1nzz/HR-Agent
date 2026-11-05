"""异步数据库引擎与会话工厂。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _to_async_url(raw_url: str) -> str:
    """把 DATABASE_URL 转成 asyncpg 驱动。

    psycopg 3 的异步模式在 Windows 默认的 ProactorEventLoop 下不可用，
    因此应用层统一使用 asyncpg；psycopg 仍供 Alembic / langchain-postgres
    的同步连接使用。
    """
    url = make_url(raw_url)
    if url.drivername in {"postgres", "postgresql", "postgresql+psycopg"}:
        url = url.set(drivername="postgresql+asyncpg")
    return url.render_as_string(hide_password=False)


engine = create_async_engine(
    _to_async_url(settings.database_url),
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_recycle=1800,
    connect_args={"timeout": 5},
)

SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：每个请求一个会话，异常时回滚。"""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def dispose_engine() -> None:
    """
    关闭数据库连接： 用于应用关闭时释放数据库连接池。
    """
    try:
        await engine.dispose()
        logger.info("数据库连接已关闭")
    except Exception as e:
        logger.error(f"关闭数据库时出错: {e}")
