"""异常处理体系测试：自定义异常、HTTPException、校验异常、数据库异常与兜底。"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException, Query, WebSocket
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from starlette.websockets import WebSocketDisconnect

from app.core.config import settings
from app.core.exceptions import (
    AppException,
    NotFoundError,
    UnauthorizedError,
)
from app.main import create_app


class Item(BaseModel):
    """用于触发请求 / 响应校验的模型。"""

    name: str = Field(min_length=2)
    age: int = Field(ge=0)


@pytest.fixture()
def exception_app() -> FastAPI:
    """在真实应用（已注册全部处理器）上挂载用于触发各类异常的测试路由。"""
    app = create_app()

    @app.get("/test/not-found")
    async def _not_found() -> None:
        raise NotFoundError("用户不存在", details={"user_id": "u-1"})

    @app.get("/test/app-error")
    async def _app_error() -> None:
        raise AppException("服务配置错误")

    @app.get("/test/app-error-details")
    async def _app_error_details() -> None:
        raise AppException("内部错误", details={"internal": "secret"})

    @app.get("/test/unauthorized")
    async def _unauthorized() -> None:
        raise UnauthorizedError(headers={"WWW-Authenticate": "Bearer"})

    @app.get("/test/http-exception")
    async def _http_exception() -> None:
        raise HTTPException(status_code=418, detail="我是茶壶")

    @app.get("/test/http-exception-default")
    async def _http_exception_default() -> None:
        raise HTTPException(status_code=404)

    @app.post("/test/validate")
    async def _validate(item: Item) -> dict[str, Any]:
        return item.model_dump()

    @app.get("/test/integrity-error")
    async def _integrity_error() -> None:
        raise IntegrityError("INSERT ...", None, Exception("duplicate key value"))

    @app.get("/test/operational-error")
    async def _operational_error() -> None:
        raise OperationalError("SELECT 1", None, Exception("connection refused"))

    @app.get("/test/sqlalchemy-error")
    async def _sqlalchemy_error() -> None:
        raise SQLAlchemyError("database exploded")

    @app.get("/test/unhandled")
    async def _unhandled() -> None:
        raise RuntimeError("secret internal detail")

    @app.get("/test/response-validation", response_model=Item)
    async def _response_validation() -> dict[str, Any]:
        return {"name": "valid", "age": "not-an-int"}

    @app.websocket("/test/ws")
    async def _ws(websocket: WebSocket, page: int = Query()) -> None:
        await websocket.accept()
        await websocket.send_text(str(page))
        await websocket.close()

    @app.websocket("/test/ws-custom-error")
    async def _ws_custom_error(websocket: WebSocket) -> None:
        await websocket.accept()
        raise NotFoundError("会话不存在")

    @app.websocket("/test/ws-app-error")
    async def _ws_app_error(websocket: WebSocket) -> None:
        await websocket.accept()
        raise AppException("内部错误")

    return app


@pytest.fixture()
def error_client(exception_app: FastAPI) -> Iterator[TestClient]:
    # 兜底 500 由 ServerErrorMiddleware 返回后会继续向上抛出，测试中关闭该行为
    with TestClient(exception_app, raise_server_exceptions=False) as client:
        yield client


def _assert_error_envelope(body: dict[str, Any], *, code: str) -> None:
    """校验统一错误响应体的公共字段。"""
    assert body["code"] == code
    assert isinstance(body["message"], str) and body["message"]
    assert body["request_id"]
    datetime.fromisoformat(body["timestamp"])


# ---------------------------------------------------------------------------
# 项目自定义异常
# ---------------------------------------------------------------------------
def test_custom_exception(error_client: TestClient) -> None:
    response = error_client.get("/test/not-found")

    assert response.status_code == 404
    body = response.json()
    _assert_error_envelope(body, code="NOT_FOUND")
    assert body["message"] == "用户不存在"
    assert body["details"] == {"user_id": "u-1"}
    assert body["request_id"] == response.headers["X-Request-ID"]
    # 处理器与中间件都写 X-Request-ID，确保没有重复
    assert response.headers.get_list("X-Request-ID") == [body["request_id"]]


def test_custom_exception_500(error_client: TestClient) -> None:
    response = error_client.get("/test/app-error")

    assert response.status_code == 500
    body = response.json()
    _assert_error_envelope(body, code="INTERNAL_ERROR")
    assert body["message"] == "服务配置错误"
    assert "Traceback" not in response.text


def test_custom_exception_headers_preserved(error_client: TestClient) -> None:
    response = error_client.get("/test/unauthorized")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["code"] == "UNAUTHORIZED"


def test_custom_exception_details_in_development(error_client: TestClient) -> None:
    response = error_client.get("/test/app-error-details")

    assert response.status_code == 500
    assert response.json()["details"] == {"internal": "secret"}


# ---------------------------------------------------------------------------
# FastAPI / Starlette 内置异常
# ---------------------------------------------------------------------------
def test_http_exception_keeps_custom_detail(error_client: TestClient) -> None:
    response = error_client.get("/test/http-exception")

    assert response.status_code == 418
    body = response.json()
    assert body["code"] == "HTTP_ERROR"
    assert body["message"] == "我是茶壶"


def test_http_exception_default_detail_is_localized(error_client: TestClient) -> None:
    response = error_client.get("/test/http-exception-default")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "NOT_FOUND"
    assert body["message"] == "请求的资源不存在"


def test_route_not_found(error_client: TestClient) -> None:
    response = error_client.get("/no-such-route")

    assert response.status_code == 404
    _assert_error_envelope(response.json(), code="NOT_FOUND")


def test_method_not_allowed(error_client: TestClient) -> None:
    response = error_client.post("/test/not-found")

    assert response.status_code == 405
    body = response.json()
    assert body["code"] == "METHOD_NOT_ALLOWED"
    assert body["message"] == "请求方法不被允许"


# ---------------------------------------------------------------------------
# 请求 / 响应校验
# ---------------------------------------------------------------------------
def test_request_validation_error(error_client: TestClient) -> None:
    response = error_client.post("/test/validate", json={"name": "x", "age": -1})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["message"] == "请求参数校验失败"

    errors = body["details"]["errors"]
    fields = {error["field"] for error in errors}
    assert {"body.name", "body.age"} <= fields
    assert all(error["message"] for error in errors)


def test_validation_error_does_not_echo_input(error_client: TestClient) -> None:
    response = error_client.post(
        "/test/validate",
        json={"name": "x", "age": "nope", "password": "super-secret"},
    )

    assert response.status_code == 422
    assert "super-secret" not in response.text


def test_response_validation_error(error_client: TestClient) -> None:
    response = error_client.get("/test/response-validation")

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "RESPONSE_VALIDATION_ERROR"
    assert body["message"] == "服务器响应数据校验失败"


def test_websocket_validation_error(exception_app: FastAPI) -> None:
    with TestClient(exception_app, raise_server_exceptions=False) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/test/ws?page=not-a-number"):
                pass

    assert exc_info.value.code == 1008


def test_websocket_custom_exception_uses_policy_violation(exception_app: FastAPI) -> None:
    with TestClient(exception_app, raise_server_exceptions=False) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/test/ws-custom-error") as websocket:
                websocket.receive_text()

    assert exc_info.value.code == 1008


def test_websocket_custom_exception_500_uses_internal_error(exception_app: FastAPI) -> None:
    with TestClient(exception_app, raise_server_exceptions=False) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/test/ws-app-error") as websocket:
                websocket.receive_text()

    assert exc_info.value.code == 1011


# ---------------------------------------------------------------------------
# SQLAlchemy 数据库异常
# ---------------------------------------------------------------------------
def test_integrity_error_maps_to_conflict(error_client: TestClient) -> None:
    response = error_client.get("/test/integrity-error")

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "DATABASE_CONFLICT"
    assert "duplicate" not in body["message"]


def test_operational_error_maps_to_unavailable(error_client: TestClient) -> None:
    response = error_client.get("/test/operational-error")

    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "DATABASE_UNAVAILABLE"


def test_sqlalchemy_error_maps_to_internal(error_client: TestClient) -> None:
    response = error_client.get("/test/sqlalchemy-error")

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "DATABASE_ERROR"
    assert body["message"] == "数据库操作失败"
    assert "database exploded" not in body["message"]


def test_production_hides_internal_details(
    exception_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "app_env", "production")

    with TestClient(exception_app, raise_server_exceptions=False) as client:
        db_response = client.get("/test/sqlalchemy-error")
        app_response = client.get("/test/app-error-details")

    assert db_response.status_code == 500
    assert "database exploded" not in db_response.text
    assert "details" not in db_response.json()

    assert app_response.status_code == 500
    assert "secret" not in app_response.text
    assert "details" not in app_response.json()


# ---------------------------------------------------------------------------
# 未知异常兜底
# ---------------------------------------------------------------------------
def test_unhandled_exception_hides_details(error_client: TestClient) -> None:
    response = error_client.get("/test/unhandled")

    assert response.status_code == 500
    body = response.json()
    _assert_error_envelope(body, code="INTERNAL_ERROR")
    assert body["message"] == "服务器内部错误"
    assert "secret internal detail" not in response.text
    assert "details" not in body


# ---------------------------------------------------------------------------
# 请求 ID 追踪
# ---------------------------------------------------------------------------
def test_request_id_is_generated(error_client: TestClient) -> None:
    response = error_client.get("/test/not-found")

    request_id = response.headers["X-Request-ID"]
    assert len(request_id) == 32
    assert response.json()["request_id"] == request_id


def test_request_id_is_propagated(error_client: TestClient) -> None:
    response = error_client.get("/test/not-found", headers={"X-Request-ID": "trace-abc.123"})

    assert response.headers["X-Request-ID"] == "trace-abc.123"
    assert response.json()["request_id"] == "trace-abc.123"


def test_invalid_request_id_is_replaced(error_client: TestClient) -> None:
    response = error_client.get("/test/not-found", headers={"X-Request-ID": "bad id!"})

    request_id = response.headers["X-Request-ID"]
    assert request_id != "bad id!"
    assert len(request_id) == 32


def test_success_response_gets_request_id(error_client: TestClient) -> None:
    response = error_client.get("/")

    assert response.status_code == 200
    assert len(response.headers["X-Request-ID"]) == 32
