"""认证接口：登录、当前用户、退出登录。

接口层只负责请求模型、状态码与响应组装；凭据校验、令牌签发等业务逻辑
位于 :mod:`app.services.auth_service`。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.db.session import get_db
from app.schemas.auth import LoginRequest, LogoutResponse, TokenResponse
from app.schemas.error import ErrorResponse
from app.schemas.user import UserRead
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

#: 登录接口在 OpenAPI 中声明的错误响应
_LOGIN_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "用户名或密码错误"},
    403: {"model": ErrorResponse, "description": "账号已被停用"},
}

#: 需要登录的接口在 OpenAPI 中声明的错误响应
_AUTH_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "缺少令牌、令牌无效或已过期"},
}


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="用户登录",
    description=(
        "使用用户名或邮箱 + 密码登录，成功返回 JWT 访问令牌与用户信息。"
        "账号不存在与密码错误返回相同的错误码，避免账号枚举。"
    ),
    responses=_LOGIN_ERROR_RESPONSES,
)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    """登录并返回访问令牌（业务逻辑见 ``auth_service.login``）。"""
    return await auth_service.login(db, payload.username, payload.password)


@router.get(
    "/me",
    response_model=UserRead,
    summary="获取当前登录用户",
    description="校验 Authorization 头中的访问令牌，返回令牌对应用户的信息。",
    responses=_AUTH_ERROR_RESPONSES,
)
async def read_current_user(current_user: CurrentUser) -> UserRead:
    """返回当前登录用户的信息（依赖已校验令牌与账号状态）。"""
    return UserRead.model_validate(current_user)


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="退出登录",
    description=("JWT 是无状态的，服务端不保存会话，此接口只做记录；客户端必须自行删除本地令牌。"),
    responses=_AUTH_ERROR_RESPONSES,
)
async def logout(current_user: CurrentUser) -> LogoutResponse:
    """记录退出事件；令牌仍会自然过期，客户端需删除本地令牌。"""
    auth_service.record_logout(current_user)
    return LogoutResponse()
