"""pytest 公共夹具与集成测试开关。

默认只跑单元测试；需要外部服务（PostgreSQL 等）的测试用：

    uv run pytest --run-integration
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="运行标记为 integration 的测试（需要 PostgreSQL / Redis 等外部服务）",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-integration"):
        return
    skip = pytest.mark.skip(reason="需要外部服务，使用 --run-integration 运行")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    """带 lifespan 的测试客户端。"""
    with TestClient(app) as test_client:
        yield test_client
