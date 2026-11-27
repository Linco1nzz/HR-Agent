"""受限规划器单元测试：规则降级与 LLM 输出校验（不依赖外部服务）。"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.core.config import settings
from app.services.agent import planner


class FakeMessage:
    """模拟 langchain 的 AIMessage：只暴露 content。"""

    def __init__(self, content: str) -> None:
        self.content = content


class FakeLLM:
    """模拟 ChatOpenAI：返回固定文本或直接抛错。"""

    def __init__(self, content: str | None = None, error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.calls: list[Any] = []

    async def ainvoke(self, messages: list[Any]) -> FakeMessage:
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        return FakeMessage(self.content or "")


# ---------------------------------------------------------------------------
# 规则降级
# ---------------------------------------------------------------------------
def test_rules_plan_extracts_jd_title() -> None:
    """「给产品经理生成 JD」→ 一个 generate_jd 步骤，标题为产品经理。"""
    result = planner.plan_with_rules("给产品经理生成一份 JD")
    assert result.source == "rules"
    assert len(result.steps) == 1
    assert result.steps[0].tool == "generate_jd"
    assert result.steps[0].args["title"] == "产品经理"


def test_rules_plan_queries_jd() -> None:
    """查询类指令 → query_resource。"""
    result = planner.plan_with_rules("列出所有 JD")
    assert result.steps[0].tool == "query_resource"
    assert result.steps[0].args["resource"] == "jd"


def test_rules_plan_falls_back_to_reply() -> None:
    """无法识别的指令给出兜底回复而不是臆造步骤。"""
    result = planner.plan_with_rules("帮我订一杯咖啡")
    assert result.steps == []
    assert result.reply == planner.FALLBACK_REPLY


def test_rules_plan_jd_without_title_asks_for_title() -> None:
    """有生成意图但没有职位名时提示补充。"""
    result = planner.plan_with_rules("帮我生成一份 JD")
    assert result.steps == []
    assert "职位名称" in (result.reply or "")


# ---------------------------------------------------------------------------
# LLM 路径
# ---------------------------------------------------------------------------
async def test_plan_uses_llm_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """合法 JSON 输出被采纳为计划。"""
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    payload = json.dumps(
        {
            "steps": [
                {
                    "tool": "query_resource",
                    "args": {"resource": "jd", "limit": 3},
                    "summary": "看看有哪些 JD",
                }
            ],
            "reply": None,
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(planner, "_build_llm", lambda: FakeLLM(payload))

    result = await planner.plan("有哪些 JD")

    assert result.source == "llm"
    assert result.steps[0].tool == "query_resource"
    assert result.steps[0].args["limit"] == 3


async def test_plan_rejects_unknown_tool_and_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM 输出未注册工具时降级到规则。"""
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    payload = json.dumps({"steps": [{"tool": "drop_database", "args": {}}]})
    monkeypatch.setattr(planner, "_build_llm", lambda: FakeLLM(payload))

    result = await planner.plan("列出所有 JD")

    assert result.source == "rules"
    assert result.steps[0].tool == "query_resource"


async def test_plan_rejects_too_many_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    """超过步骤上限的输出不被采纳。"""
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    steps = [
        {"tool": "query_resource", "args": {"resource": "jd"}}
        for _ in range(planner.registry.MAX_PLAN_STEPS + 1)
    ]
    monkeypatch.setattr(
        planner,
        "_build_llm",
        lambda: FakeLLM(json.dumps({"steps": steps})),
    )

    result = await planner.plan("列出所有 JD")

    assert result.source == "rules"


async def test_plan_falls_back_on_llm_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """模型调用异常时降级到规则。"""
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(
        planner,
        "_build_llm",
        lambda: FakeLLM(error=RuntimeError("boom")),
    )

    result = await planner.plan("列出所有 JD")

    assert result.source == "rules"
    assert result.steps[0].tool == "query_resource"


async def test_plan_without_key_uses_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    """未配置模型时直接走规则，不发起网络请求。"""
    monkeypatch.setattr(settings, "deepseek_api_key", None)

    result = await planner.plan("列出所有 JD")

    assert result.source == "rules"
    assert result.steps[0].tool == "query_resource"


async def test_plan_llm_reply_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """模型判定无法执行时返回 reply，不产生步骤。"""
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    payload = json.dumps({"steps": [], "reply": "请先告诉我要生成什么"}, ensure_ascii=False)
    monkeypatch.setattr(planner, "_build_llm", lambda: FakeLLM(payload))

    result = await planner.plan("随便聊聊")

    assert result.steps == []
    assert result.reply == "请先告诉我要生成什么"
