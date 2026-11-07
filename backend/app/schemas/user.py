"""用户相关的响应模型。

只暴露可以安全返回给客户端的字段：``hashed_password`` 等敏感列绝不出现在
模型里，避免误通过 ``response_model`` 泄露。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserRead(BaseModel):
    """对外暴露的用户信息（登录响应与当前用户接口共用）。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="用户 ID")
    username: str = Field(description="用户名")
    email: EmailStr = Field(description="邮箱地址")
    full_name: str | None = Field(default=None, description="用户全名")
    phone: str | None = Field(default=None, description="手机号")
    department: str | None = Field(default=None, description="所属部门")
    position: str | None = Field(default=None, description="职位")
    employee_id: str | None = Field(default=None, description="员工编号")
    is_superuser: bool = Field(description="是否为超级管理员")
    is_verified: bool = Field(description="是否已验证")
    is_active: bool = Field(description="是否启用")
    bio: str | None = Field(default=None, description="个人简介")
    avatar_url: str | None = Field(default=None, description="头像地址")
    last_login: datetime | None = Field(default=None, description="最后登录时间")
    roles: list[str] = Field(default_factory=list, description="角色名称列表")

    @field_validator("roles", mode="before")
    @classmethod
    def _role_names(cls, value: Any) -> Any:
        """把 ORM ``Role`` 对象列表转换为角色名列表。"""
        if value is None:
            return []
        return [getattr(role, "name", str(role)) for role in value]
