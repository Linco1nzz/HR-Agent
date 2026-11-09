"""FastAPI 公共依赖：从 ``Authorization: Bearer <token>`` 解析当前登录用户。

这里只处理 HTTP 细节（读取请求头、抛出统一异常），令牌与用户校验逻辑
位于 :mod:`app.services.auth_service`。
"""

from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidTokenError
from app.db.models import User
from app.db.session import get_db
from app.services import auth_service, dify_service

#: ``auto_error=False``：缺少 / 格式错误的 Authorization 头也交给本模块处理，
#: 以保持错误响应格式与错误码统一。
bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="BearerAuth",
    description="登录接口返回的 JWT 访问令牌",
)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """校验访问令牌并返回对应用户（具体规则见 ``auth_service.resolve_user_from_token``）。"""
    if credentials is None:
        raise InvalidTokenError("缺少访问令牌，请先登录")
    return await auth_service.resolve_user_from_token(db, credentials.credentials)


#: 需要登录的接口直接声明 ``current_user: CurrentUser``
CurrentUser = Annotated[User, Depends(get_current_user)]

#: Dify HTTP 客户端（进程内复用；测试中可覆盖 ``dify_service.get_client``）
DifyClient = Annotated[httpx.AsyncClient, Depends(dify_service.get_client)]
