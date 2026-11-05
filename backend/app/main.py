"""FastAPI 应用入口：uv run uvicorn app.main:app --reload"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings

from app.core.logging import setup_logging, get_logger
from app.db.session import dispose_engine

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """应用生命周期：启动日志 / 退出时释放连接池。"""
    logger.info(
        "application_startup",
        app=settings.app_name,
        environment=settings.app_env,
        debug=settings.debug,
    )
    yield
    await dispose_engine()
    logger.info("application_shutdown")


def create_app() -> FastAPI:
    """工厂函数：便于测试与多实例部署。"""
    docs_enabled = not settings.is_production

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="HR Agent - AI驱动的人力资源助手",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
            "health": f"{settings.api_v1_prefix}/health",
        }

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app", 
        host=settings.host, 
        port=settings.port, 
        reload=settings.debug, 
        log_level=settings.log_level.lower()
    )