"""统一错误响应模型。

异常处理器（``app.core.exception_handlers``）与 OpenAPI 文档共用这份结构，
保证文档描述与真实返回一致。前端可只依赖 ``code`` 做分支，``message`` 用于展示。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class FieldError(BaseModel):
    """单条字段级错误（请求 / 响应校验失败时使用）。"""

    field: str = Field(description="出错字段路径，如 body.email 或 query.page")
    message: str = Field(description="错误说明")
    type: str | None = Field(default=None, description="校验器类型，如 value_error")


class ErrorResponse(BaseModel):
    """所有接口出错时返回的统一结构。"""

    code: str = Field(
        description="稳定的错误码，取值见 app.core.error_codes.ErrorCode",
        examples=["NOT_FOUND"],
    )
    message: str = Field(description="面向调用方的错误说明", examples=["用户不存在"])
    details: dict[str, Any] | None = Field(
        default=None,
        description="附加上下文，如校验错误明细 details.errors；生产环境不返回内部异常细节",
    )
    request_id: str | None = Field(
        default=None,
        description="请求追踪 ID，同时出现在响应头 X-Request-ID",
        examples=["4f8a2c9d1e6b47f5a3c0d7e8b9a1c2d3"],
    )
    timestamp: datetime = Field(description="错误发生时间（UTC）")
