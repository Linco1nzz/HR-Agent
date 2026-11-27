"""受限规划器：把一条自然语言指令拆成白名单内的工具步骤。

优先用 DeepSeek 输出严格 JSON（工具名与参数都要通过注册表校验），模型不可用、
输出不合法或超时都降级到关键词规则；任何越权工具与越权参数都会被后端拒绝。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.core.logging import get_logger
from app.services.agent import registry

logger = get_logger(__name__)

#: 无法拆解时的兜底回复
FALLBACK_REPLY = (
    "这条指令我还理解不了。我可以帮你：生成 JD、生成简历评分标准、"
    "对简历评分、生成面试方案，或查询现有资源。请说得更具体一些。"
)

_SYSTEM_PROMPT = """你是 HR Agent 的 ReAct 控制器。你要按 Thought -> Action -> Observation 的方式，为当前用户消息选择下一步动作。

规则：
1. 只能使用给定工具；不得臆造工具名。
2. 参数必须符合工具的 JSON Schema；资源 ID 只能来自用户输入，不能编造。
3. 一条任务最多 {max_steps} 个步骤。
4. 如果无法完成，返回 steps 为空数组，并在 reply 中给出简短说明。
5. 只输出 JSON，不要输出 Markdown 代码块或解释。

输出格式：
{{"steps": [{{"tool": "<工具名>", "args": {{...}}, "summary": "<一句话说明>"}}], "reply": null}}

可用工具：
{tools}
"""

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)
_JD_TITLE_PATTERNS = (
    re.compile(r"JD[：:\s]+([^\s，,。；;]{2,30})"),
    re.compile(r"(?:给|为|帮)\s*([^\s，,。；;]{2,20}?)(?:岗位|职位)?\s*(?:生成|写|起草|出一份)"),
    re.compile(
        r"(?:生成|写|起草)(?:一份|一个|个)?\s*([^\s，,。；;]{2,20}?)(?:岗位|职位)?(?:的)?\s*JD"
    ),
)
_JD_KEYWORD = re.compile(r"(JD|职位描述|job\s*description)", re.IGNORECASE)
_TITLE_PREFIX = re.compile(r"^(?:请|帮我|帮忙|我|我们|你|您|给|为|按)+")
#: 误抓到的量词 / 泛指，不作为职位名
_TITLE_STOPWORDS = frozenset({"一份", "一个", "职位", "岗位", "招聘", "这个", "那个", "下"})
_GENERATE_VERB = re.compile(r"(生成|写|起草|拟一份|出一份)")
_QUERY_PATTERNS: tuple[tuple[re.Pattern[str], dict[str, Any]], ...] = (
    (re.compile(r"(有哪些|列出|查询|看看|找).*(JD|职位)", re.IGNORECASE), {"resource": "jd"}),
    (
        re.compile(r"(有哪些|列出|查询|看看|找).*(评分标准)", re.IGNORECASE),
        {"resource": "scoring_criteria"},
    ),
    (
        re.compile(r"(有哪些|列出|查询|看看|找).*(简历|候选人)", re.IGNORECASE),
        {"resource": "resume_evaluation"},
    ),
    (
        re.compile(r"(有哪些|列出|查询|看看|找).*(面试方案|面试)", re.IGNORECASE),
        {"resource": "interview_plan"},
    ),
)


@dataclass(slots=True)
class PlannedStep:
    """Planner 产出的单个步骤。"""

    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    summary: str = ""


@dataclass(slots=True)
class PlanResult:
    """规划结果：steps 为空时用 reply 作为兜底回复。"""

    steps: list[PlannedStep] = field(default_factory=list)
    reply: str | None = None
    source: str = "llm"


def _build_llm() -> ChatOpenAI:
    """规划用的非流式模型（与问答服务同款配置）。"""
    return ChatOpenAI(
        model=settings.deepseek_model,
        openai_api_key=settings.deepseek_api_key,
        openai_api_base=settings.deepseek_base_url,
        temperature=0,
        timeout=settings.deepseek_timeout_seconds,
        max_tokens=settings.deepseek_max_tokens,
        reasoning_effort=settings.deepseek_reasoning_effort,
    )


def _build_prompt(message: str) -> str:
    """拼装系统提示词：工具目录 + 步骤上限。"""
    tools = json.dumps(registry.tool_catalog(), ensure_ascii=False, indent=2)
    return _SYSTEM_PROMPT.format(max_steps=registry.MAX_PLAN_STEPS, tools=tools)


def _parse_json_object(text: str) -> dict[str, Any] | None:
    """从模型输出里提取第一个 JSON 对象。"""
    match = _JSON_BLOCK.search(text)
    if match is None:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _validate_model_output(data: dict[str, Any]) -> list[PlannedStep]:
    """把模型输出收敛成合法的 PlannedStep 列表；不合法直接抛 ValueError。"""
    raw_steps = data.get("steps")
    if raw_steps is None:
        raw_steps = []
    if not isinstance(raw_steps, list):
        raise ValueError("steps 必须是数组")
    if len(raw_steps) > registry.MAX_PLAN_STEPS:
        raise ValueError(f"步骤数不能超过 {registry.MAX_PLAN_STEPS}")

    steps: list[PlannedStep] = []
    for raw in raw_steps:
        if not isinstance(raw, dict):
            raise ValueError("步骤必须是对象")
        tool = raw.get("tool")
        args = raw.get("args") or {}
        if not isinstance(tool, str) or not isinstance(args, dict):
            raise ValueError("步骤缺少 tool / args")
        registry.validate_tool_args(tool, args)
        summary = raw.get("summary")
        steps.append(
            PlannedStep(
                tool=tool,
                args=args,
                summary=summary.strip()[:200] if isinstance(summary, str) else "",
            )
        )
    return steps


def _extract_jd_title(message: str) -> str | None:
    """从「给产品经理生成 JD」这类指令里提取职位名称。"""
    for pattern in _JD_TITLE_PATTERNS:
        match = pattern.search(message)
        if match is None:
            continue
        title = match.group(1).strip(" 的岗位职位")
        title = _TITLE_PREFIX.sub("", title).strip(" 的")
        if len(title) < 2 or title in _TITLE_STOPWORDS:
            continue
        if len(title) <= 255:
            return title
    return None


def plan_with_rules(message: str) -> PlanResult:
    """确定性降级：识别最常见的单步指令。"""
    text = message.strip()
    if _JD_KEYWORD.search(text) and _GENERATE_VERB.search(text):
        title = _extract_jd_title(text)
        if title:
            return PlanResult(
                steps=[PlannedStep("generate_jd", {"title": title}, f"生成 {title} 的 JD")],
                source="rules",
            )
        return PlanResult(
            reply="生成 JD 需要先告诉我职位名称，例如：给产品经理生成一份 JD。",
            source="rules",
        )
    for pattern, args in _QUERY_PATTERNS:
        if pattern.search(text):
            return PlanResult(
                steps=[PlannedStep("query_resource", args, "查询资源")],
                source="rules",
            )
    return PlanResult(reply=FALLBACK_REPLY, source="rules")


async def plan(message: str) -> PlanResult:
    """规划一条指令；模型不可用或输出非法时降级到规则。"""
    if not settings.deepseek_api_key:
        logger.warning("agent_plan_llm_unconfigured")
        return plan_with_rules(message)

    try:
        response = await _build_llm().ainvoke(
            [SystemMessage(content=_build_prompt(message)), HumanMessage(content=message)]
        )
        content = response.content if isinstance(response.content, str) else str(response.content)
        data = _parse_json_object(content)
        if data is None:
            raise ValueError("模型输出不是 JSON 对象")
        steps = _validate_model_output(data)
        reply = data.get("reply")
        if not steps:
            return PlanResult(
                reply=reply.strip()[:500] if isinstance(reply, str) and reply.strip() else None,
                source="llm",
            )
        logger.info("agent_plan_generated", steps=[step.tool for step in steps])
        return PlanResult(steps=steps, source="llm")
    except Exception as exc:
        logger.warning("agent_plan_llm_fallback", error=str(exc))
        return plan_with_rules(message)
