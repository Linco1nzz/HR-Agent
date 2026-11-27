"""pytest 公共夹具与集成测试开关。

默认只跑单元测试；需要外部服务（PostgreSQL 等）的测试用：

    uv run pytest --run-integration
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

# 单元测试不依赖外部服务：在导入应用前切换为 testing 环境，跳过启动期的
# Agent 任务恢复扫描（该扫描需要数据库）。
os.environ.setdefault("APP_ENV", "testing")

from app.main import app  # noqa: E402 - 必须在设置环境变量之后导入


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
