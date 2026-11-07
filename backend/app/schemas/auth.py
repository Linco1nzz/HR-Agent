"""认证相关的请求 / 响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.user import UserRead


class LoginRequest(BaseModel):
    """登录请求：``username`` 可以是用户名或邮箱。"""

    username: str = Field(
        min_length=1,
        max_length=255,
        description="用户名或邮箱地址（邮箱大小写不敏感）",
        examples=["testuser"],
    )
    password: str = Field(
        min_length=1,
        max_length=256,
        description="密码",
        examples=["test123"],
    )

    @field_validator("username")
    @classmethod
    def _strip_username(cls, value: str) -> str:
        """去掉首尾空白；全空白视为非法输入。"""
        stripped = value.strip()
        if not stripped:
            raise ValueError("账号不能为空")
        return stripped


class TokenResponse(BaseModel):
    """登录成功响应：访问令牌 + 登录用户信息。"""

    access_token: str = Field(description="JWT 访问令牌")
    token_type: Literal["bearer"] = Field(default="bearer", description="令牌类型")
    expires_in: int = Field(description="令牌有效期（秒）")
    user: UserRead = Field(description="登录用户信息")


class LogoutResponse(BaseModel):
    """退出登录响应。

    JWT 是无状态的，服务端不保存会话；客户端需自行删除本地令牌。
    """

    message: str = Field(default="已退出登录", description="提示信息")
