"""健康检查与基础路由测试（不依赖外部服务）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings


def test_root(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == settings.app_name
    assert body["health"] == f"{settings.api_v1_prefix}/health"


def test_liveness(client: TestClient) -> None:
    response = client.get(f"{settings.api_v1_prefix}/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["environment"] == settings.app_env


def test_openapi_available(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert f"{settings.api_v1_prefix}/health" in paths


@pytest.mark.integration
def test_readiness_with_database(client: TestClient) -> None:
    """需要 Docker 中的 PostgreSQL（uv run pytest -m integration）。"""
    response = client.get(f"{settings.api_v1_prefix}/health/ready")
    assert response.status_code == 200
    assert response.json()["database"] == "up"
