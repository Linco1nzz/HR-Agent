"""知识库问答编排：路由 → 改写 → 混合检索 → rerank → 流式回答 → 落库。

``chat`` 是供 SSE 端点消费的 async generator，yield ``(event_name, dict)``，
事件序列为 ``meta → (sources) → delta* → done | error``。

流式期间请求级会话可能已关闭，因此所有数据库操作都通过
``app.db.session.SessionLocal`` 自建会话，每个持久化步骤独立会话。
路由 / 改写 / 检索 / rerank 任一环节失败都有降级路径，只有回答模型不可用
或流式中断才产出 ``error`` 事件。
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_openai import ChatOpenAI
from sqlalchemy import select

from app.core.config import settings
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppException, QaNotConfiguredError
from app.core.logging import get_logger
from app.db.models import Conversation, KnowledgeBase, Message, User
from app.db.session import SessionLocal
from app.services import conversation_service, kb_retrieval_service, rerank_service

# 复用文档切块服务中经过实战检验的 LLM 文本提取与健壮 JSON 解析
from app.services.document_chunking_service import _extract_json, _message_text
from app.services.kb_retrieval_service import RetrievedChunk

logger = get_logger(__name__)

_ROUTE_SYSTEM_PROMPT = (
    "你是 HR 助手的问题路由器。根据用户问题、对话历史与知识库主题列表，"
    "判断回答该问题是否需要检索知识库。\n"
    "规则：寒暄、闲聊、通用常识、与所列知识库主题无关的问题 use_kb=false；"
    "可能涉及知识库内容的问题（如公司制度、员工手册、考勤、假期、薪酬、福利、"
    "入离职流程等）use_kb=true。\n"
    '只输出 JSON：{"use_kb": true 或 false, "reason": "简短理由"}'
)

_ENHANCE_SYSTEM_PROMPT = (
    "你是知识库检索的查询改写助手。请结合对话历史，对用户最新问题做指代消解，"
    "改写成一句独立、完整、适合检索的查询；再提取 3~8 个检索关键词"
    "（包含同义扩展，覆盖问题的核心概念）。\n"
    '只输出 JSON：{"rewritten_query": "...", "keywords": ["...", "..."]}'
)

_KB_ANSWER_SYSTEM_PROMPT = (
    "你是专业、友好的 HR 助手。请基于下方编号来源回答用户问题。\n"
    "要求：\n"
    "1. 回答必须基于来源内容，并在相应位置用 [n] 标注引用（n 为来源编号）；\n"
    "2. 来源不足以回答时，明确说明知识库中未找到相关内容，不要编造；\n"
    "3. 用简体中文回答，条理清晰。"
)

_KB_NO_SOURCE_SYSTEM_PROMPT = (
    "你是专业、友好的 HR 助手。本次检索未在知识库中找到与问题相关的内容。"
    "请先明确告知用户知识库中未找到相关资料，再基于通用知识谨慎回答，"
    "并提示答案仅供参考、以公司正式制度为准。用简体中文回答。"
)

_DIRECT_SYSTEM_PROMPT = (
    "你是专业、友好的 HR 助手，擅长人力资源领域的问题。"
    "请直接回答用户的问题；寒暄闲聊时自然、礼貌地回应。用简体中文回答。"
)


@dataclass(slots=True)
class KbBrief:
    """路由用的知识库摘要。"""

    name: str
    description: str | None


@dataclass(slots=True)
class _ChatContext:
    """一轮问答开始时从数据库加载的会话快照。"""

    conversation_id: UUID
    knowledge_base_ids: list[UUID]
    kb_briefs: list[KbBrief]
    #: (role, content) 列表，按时间升序，最多 qa_history_turns 轮
    history: list[tuple[str, str]]
    last_message_id: UUID | None


# ---------------------------------------------------------------------------
# LLM 基础设施
# ---------------------------------------------------------------------------
def _build_chat_model() -> ChatOpenAI:
    """路由 / 改写用的非流式模型（与文档切块服务同款参数）。"""
    return ChatOpenAI(
        model=settings.deepseek_model,
        openai_api_key=settings.deepseek_api_key,
        openai_api_base=settings.deepseek_base_url,
        temperature=0,
        timeout=settings.deepseek_timeout_seconds,
        max_tokens=settings.deepseek_max_tokens,
        reasoning_effort=settings.deepseek_reasoning_effort,
    )


def _build_answer_model() -> ChatOpenAI:
    """回答用的流式模型；stream_usage 尽力拿 token 统计。"""
    return ChatOpenAI(
        model=settings.deepseek_model,
        openai_api_key=settings.deepseek_api_key,
        openai_api_base=settings.deepseek_base_url,
        temperature=settings.qa_temperature,
        timeout=settings.deepseek_timeout_seconds,
        max_tokens=settings.qa_max_answer_tokens,
        reasoning_effort=settings.deepseek_reasoning_effort,
        streaming=True,
        stream_usage=True,
    )


def _format_history(history: list[tuple[str, str]]) -> str:
    """把最近若干轮历史拼成提示词文本。"""
    recent = history[-(settings.qa_history_turns * 2) :]
    lines = []
    for role, content in recent:
        speaker = "用户" if role == "user" else "助手"
        lines.append(f"{speaker}: {content}")
    return "\n".join(lines) if lines else "（无历史对话）"


# ---------------------------------------------------------------------------
# 路由与查询改写
# ---------------------------------------------------------------------------
async def route_question(
    question: str,
    kb_briefs: list[KbBrief],
    history: list[tuple[str, str]],
) -> dict[str, Any]:
    """判断是否需要检索知识库；失败时保守回退（有知识库则走检索）。"""
    fallback: dict[str, Any] = {
        "use_kb": bool(kb_briefs),
        "reason": "路由模型不可用，按默认策略处理",
    }
    if not settings.deepseek_api_key:
        return fallback

    kb_lines = "\n".join(
        f"- {brief.name}：{brief.description or '（无描述）'}" for brief in kb_briefs
    )
    prompt = (
        f"知识库列表：\n{kb_lines}\n\n"
        f"对话历史：\n{_format_history(history)}\n\n"
        f"用户最新问题：{question}"
    )
    try:
        response = await _build_chat_model().ainvoke(
            [SystemMessage(content=_ROUTE_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
        data = _extract_json(_message_text(response.content))
        if isinstance(data, dict) and "use_kb" in data:
            use_kb = data["use_kb"]
            if isinstance(use_kb, str):
                use_kb = use_kb.strip().lower() in {"true", "1", "yes"}
            return {"use_kb": bool(use_kb), "reason": str(data.get("reason", ""))}
        logger.warning("qa_route_parse_failed")
        return fallback
    except Exception as exc:  # noqa: BLE001 - 路由失败走保守回退
        logger.warning("qa_route_failed", error=str(exc))
        return fallback


async def enhance_query(question: str, history: list[tuple[str, str]]) -> dict[str, Any]:
    """指代消解改写 + 关键词提取；失败时回退原问题与空关键词。"""
    fallback: dict[str, Any] = {"rewritten_query": question, "keywords": []}
    if not settings.deepseek_api_key:
        return fallback

    prompt = f"对话历史：\n{_format_history(history)}\n\n用户最新问题：{question}"
    try:
        response = await _build_chat_model().ainvoke(
            [SystemMessage(content=_ENHANCE_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
        data = _extract_json(_message_text(response.content))
        if not isinstance(data, dict):
            logger.warning("qa_enhance_parse_failed")
            return fallback
        rewritten = str(data.get("rewritten_query") or "").strip() or question
        raw_keywords = data.get("keywords")
        keywords: list[str] = []
        if isinstance(raw_keywords, list):
            for item in raw_keywords:
                if isinstance(item, str) and item.strip() and item.strip() not in keywords:
                    keywords.append(item.strip())
        return {"rewritten_query": rewritten, "keywords": keywords[:8]}
    except Exception as exc:  # noqa: BLE001 - 改写失败回退原问题
        logger.warning("qa_enhance_failed", error=str(exc))
        return fallback


# ---------------------------------------------------------------------------
# 回答生成
# ---------------------------------------------------------------------------
def build_answer_messages(
    question: str,
    *,
    history: list[tuple[str, str]],
    sources: list[dict[str, Any]],
    route: str,
) -> list[BaseMessage]:
    """组装回答提示词：KB 路带编号来源，direct 路普通 HR 助手人设。"""
    if route == "kb":
        if sources:
            source_text = "\n\n".join(
                f"[{index}] 文档：{source['document_name']}\n{source['content']}"
                for index, source in enumerate(sources, start=1)
            )
            system_prompt = f"{_KB_ANSWER_SYSTEM_PROMPT}\n\n来源：\n{source_text}"
        else:
            system_prompt = _KB_NO_SOURCE_SYSTEM_PROMPT
    else:
        system_prompt = _DIRECT_SYSTEM_PROMPT

    messages: list[BaseMessage] = [SystemMessage(content=system_prompt)]
    for role, content in history[-(settings.qa_history_turns * 2) :]:
        if role == "user":
            messages.append(HumanMessage(content=content))
        else:
            messages.append(AIMessage(content=content))
    messages.append(HumanMessage(content=question))
    return messages


async def stream_answer(
    question: str,
    *,
    history: list[tuple[str, str]],
    sources: list[dict[str, Any]],
    route: str,
) -> AsyncIterator[AIMessageChunk]:
    """流式生成回答，逐块产出 LangChain 消息块。"""
    model = _build_answer_model()
    messages = build_answer_messages(question, history=history, sources=sources, route=route)
    async for chunk in model.astream(messages):
        yield chunk


def _source_dict(chunk: RetrievedChunk, score: float) -> dict[str, Any]:
    """SSE sources 事件与消息 context 中的来源结构。"""
    return {
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "document_name": chunk.document_name,
        "knowledge_base_id": chunk.knowledge_base_id,
        "chunk_index": chunk.chunk_index,
        "content": chunk.content,
        "score": score,
    }


# ---------------------------------------------------------------------------
# 数据库步骤（每步独立会话，不依赖请求级 get_db）
# ---------------------------------------------------------------------------
async def _load_chat_context(conversation_id: UUID, *, user: User) -> _ChatContext:
    """校验会话归属并加载知识库摘要、历史与最后一条消息 ID。"""
    async with SessionLocal() as db:
        conversation = await conversation_service.get_conversation(db, conversation_id, user=user)
        kb_ids = [UUID(raw) for raw in conversation.knowledge_base_ids or []]
        kb_briefs: list[KbBrief] = []
        valid_kb_ids: list[UUID] = []
        if kb_ids:
            stmt = select(KnowledgeBase).where(
                KnowledgeBase.id.in_(kb_ids), KnowledgeBase.is_active.is_(True)
            )
            records = (await db.scalars(stmt)).all()
            by_id = {record.id: record for record in records}
            for kb_id in kb_ids:
                record = by_id.get(kb_id)
                if record is not None:
                    valid_kb_ids.append(kb_id)
                    kb_briefs.append(KbBrief(name=record.name, description=record.description))

        history_stmt = (
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.role.in_(["user", "assistant"]),
            )
            .order_by(Message.created_at.desc())
            .limit(settings.qa_history_turns * 2)
        )
        rows = list((await db.scalars(history_stmt)).all())
        history = [(row.role, row.content) for row in reversed(rows)]
        last_message_id = await db.scalar(
            select(Message.id)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
    return _ChatContext(
        conversation_id=conversation_id,
        knowledge_base_ids=valid_kb_ids,
        kb_briefs=kb_briefs,
        history=history,
        last_message_id=last_message_id,
    )


async def _persist_user_message(
    ctx: _ChatContext,
    content: str,
    *,
    user_message_id: UUID,
    user_id: UUID,
) -> None:
    async with SessionLocal() as db:
        db.add(
            Message(
                id=user_message_id,
                conversation_id=ctx.conversation_id,
                role="user",
                content=content,
                parent_message_id=ctx.last_message_id,
                created_by=user_id,
                updated_by=user_id,
            )
        )
        await db.commit()


async def _persist_assistant_message(
    ctx: _ChatContext,
    *,
    message_id: UUID,
    user_message_id: UUID,
    content: str,
    tokens_used: int | None,
    response_time: float,
    context: dict[str, Any],
    first_user_content: str,
    user_id: UUID,
    error: str | None = None,
) -> None:
    """落库助手消息，并更新消息总数、自动标题与会话更新时间。"""
    async with SessionLocal() as db:
        db.add(
            Message(
                id=message_id,
                conversation_id=ctx.conversation_id,
                role="assistant",
                content=content,
                model_name=settings.deepseek_model,
                tokens_used=tokens_used,
                response_time=response_time,
                context=context,
                meta_data={"error": error} if error else None,
                parent_message_id=user_message_id,
                created_by=user_id,
                updated_by=user_id,
            )
        )
        await conversation_service.update_total_messages(db, ctx.conversation_id)
        conversation = await db.get(Conversation, ctx.conversation_id)
        if conversation is not None:
            conversation_service.auto_title(conversation, first_user_content)
            conversation.updated_by = user_id
        await db.commit()


# ---------------------------------------------------------------------------
# chat 编排
# ---------------------------------------------------------------------------
async def chat(
    conversation_id: UUID,
    content: str,
    *,
    user: User,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """一轮问答的 SSE 事件流：meta → (sources) → delta* → done | error。"""
    user_id = user.id
    user_message_id = uuid4()
    assistant_message_id = uuid4()
    fragments: list[str] = []
    tokens_used: int | None = None
    user_message_saved = False
    ctx: _ChatContext | None = None
    context: dict[str, Any] = {}
    started = time.perf_counter()

    try:
        ctx = await _load_chat_context(conversation_id, user=user)
        if not settings.deepseek_api_key:
            raise QaNotConfiguredError()

        # 1) 路由：无绑定知识库直接 direct，有则交给 LLM 判断
        if not ctx.kb_briefs:
            route, reason = "direct", "会话未绑定知识库"
        else:
            decision = await route_question(content, ctx.kb_briefs, ctx.history)
            route = "kb" if decision["use_kb"] else "direct"
            reason = decision["reason"]

        # 2) KB 路：改写 → 混合检索 → rerank → 来源
        rewritten_query, keywords = content, []
        sources: list[dict[str, Any]] = []
        if route == "kb":
            enhanced = await enhance_query(content, ctx.history)
            rewritten_query = enhanced["rewritten_query"]
            keywords = enhanced["keywords"]
            candidates = await kb_retrieval_service.retrieve(
                rewritten_query, keywords, ctx.knowledge_base_ids
            )
            ranked = await rerank_service.rerank(rewritten_query, candidates)
            sources = [_source_dict(chunk, score) for chunk, score in ranked]
        context = {
            "route": route,
            "reason": reason,
            "rewritten_query": rewritten_query,
            "keywords": keywords,
            "sources": sources,
        }

        # 3) 先持久化用户消息，再预告两条消息的 ID
        await _persist_user_message(ctx, content, user_message_id=user_message_id, user_id=user_id)
        user_message_saved = True
        yield (
            "meta",
            {
                "user_message_id": str(user_message_id),
                "assistant_message_id": str(assistant_message_id),
                "route": route,
                "reason": reason,
                "rewritten_query": rewritten_query,
                "keywords": keywords,
            },
        )
        if route == "kb":
            yield "sources", {"sources": sources}

        # 4) 流式回答
        async for chunk in stream_answer(
            content, history=ctx.history, sources=sources, route=route
        ):
            usage = getattr(chunk, "usage_metadata", None)
            if usage and usage.get("total_tokens") is not None:
                tokens_used = int(usage["total_tokens"])
            text = _message_text(chunk.content)
            if text:
                fragments.append(text)
                yield "delta", {"content": text}

        response_time = time.perf_counter() - started
        await _persist_assistant_message(
            ctx,
            message_id=assistant_message_id,
            user_message_id=user_message_id,
            content="".join(fragments),
            tokens_used=tokens_used,
            response_time=response_time,
            context=context,
            first_user_content=content,
            user_id=user_id,
        )
        logger.info(
            "qa_chat_finished",
            conversation_id=str(conversation_id),
            route=route,
            sources=len(sources),
            tokens_used=tokens_used,
            response_time=round(response_time, 3),
        )
        yield (
            "done",
            {
                "message_id": str(assistant_message_id),
                "tokens_used": tokens_used,
                "response_time": response_time,
                "model_name": settings.deepseek_model,
            },
        )
    except Exception as exc:  # noqa: BLE001 - 流式期间异常统一转 error 事件
        if isinstance(exc, AppException):
            logger.warning(
                "qa_chat_failed",
                conversation_id=str(conversation_id),
                code=exc.code.value,
                error=exc.message,
            )
            code, message = exc.code.value, exc.message
        else:
            logger.exception("qa_chat_unexpected_error", conversation_id=str(conversation_id))
            code, message = ErrorCode.QA_STREAM_FAILED.value, "回答生成失败，请稍后重试"

        # 已有部分内容时保留助手消息，并在 meta_data 记录错误
        if ctx is not None and user_message_saved and fragments:
            try:
                await _persist_assistant_message(
                    ctx,
                    message_id=assistant_message_id,
                    user_message_id=user_message_id,
                    content="".join(fragments),
                    tokens_used=tokens_used,
                    response_time=time.perf_counter() - started,
                    context=context,
                    first_user_content=content,
                    user_id=user_id,
                    error=str(exc),
                )
            except Exception:  # noqa: BLE001 - 落库失败不应掩盖原始错误
                logger.exception(
                    "qa_chat_partial_persist_failed", conversation_id=str(conversation_id)
                )
        yield "error", {"code": code, "message": message}
