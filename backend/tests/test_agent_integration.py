"""真实依赖集成冒烟：Agent 工具复用的 Dify JD 生成链路（需 ``--run-integration``）。

只验证「现有 Dify 调用逻辑能被 Agent 工具直接复用」这一关键假设，不写数据库、
不经过 HTTP；运行前需本机 Dify 可用且 ``DIFY_API_KEY`` 有效。
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.config import settings
from app.schemas.jd import GenerateJDRequest
from app.services import jd_service
from app.services.agent import tools

pytestmark = pytest.mark.integration


@pytest.mark.skipif(not settings.dify_api_key, reason="未配置 DIFY_API_KEY")
async def test_dify_jd_stream_through_agent_tools() -> None:
    """流式生成 JD：能收到增量文本、完整正文与 done 载荷。"""
    deltas: list[str] = []

    async def on_delta(text: str) -> None:
        deltas.append(text)

    stream = jd_service.stream_generate_jd(
        GenerateJDRequest(title="测试工程师"),
        user_id=uuid4(),
        client=None,
    )
    content, done = await tools.consume_generation(stream, on_delta)

    assert content.strip()
    assert "测试工程师" in content
    assert deltas, "应至少收到一条增量文本"
    assert done.get("workflow_type") == "jd_generation"
