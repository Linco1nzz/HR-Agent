"""文档切块：LLM 语义分割点 + LangChain 递归切分 + 长度约束。

流程：

1. 把正文按空行（无空行时按行）拆成带字符偏移的段落；
2. 文本足够长且配置了 LLM 时，请模型标出「主题发生切换」的段落序号，作为
   语义分割点，把正文切成若干语义段；LLM 未配置或调用失败时退化为整篇切分；
3. 每个语义段交给 LangChain 的 :class:`RecursiveCharacterTextSplitter`，按
   中英文标点递归切分，受 ``CHUNK_SIZE`` / ``CHUNK_OVERLAP`` 约束；
4. 过短的分块并入前一块，最终块数超过 ``KNOWLEDGE_BASE_MAX_CHUNKS`` 时截断。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings
from app.core.exceptions import DocumentProcessingError
from app.core.logging import get_logger

logger = get_logger(__name__)

#: 少于该长度的文本不调用 LLM，直接按递归切分处理
MIN_LLM_SPLIT_CHARS = 1_200
#: 参与 LLM 判断的最大段落数
MAX_LLM_PARAGRAPHS = 200
_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_SPLIT_KEYS = (
    "split_points",
    "splitPoints",
    "points",
    "indices",
    "boundaries",
    "分割点",
    "分块起点",
)

_SYSTEM_PROMPT = (
    "你是文档结构化助手，负责为检索增强生成（RAG）寻找语义分块边界。"
    "只输出 JSON，不要解释，不要输出 Markdown 代码块以外的内容。"
)
_USER_PROMPT_TEMPLATE = """下面是一份文档按顺序编号后的段落。请找出「主题发生明显切换」、
适合作为新分块起点的段落序号（不要包含第 1 段）。

判断依据：章节标题切换、主题明显变化、问答条目或表格条目切换。
如果全文主题一致，返回空列表。

只输出 JSON：{{"split_points": [段落序号, ...]}}

段落：
{paragraphs}
"""


@dataclass(slots=True)
class _Paragraph:
    """带字符偏移的段落，用于把 LLM 返回的序号映射回正文位置。"""

    text: str
    start: int


def _build_splitter() -> RecursiveCharacterTextSplitter:
    """中英文混排的递归切分器：优先段落，再句号 / 问号 / 逗号。"""
    chunk_size = settings.knowledge_base_chunk_size
    overlap = min(settings.knowledge_base_chunk_overlap, max(chunk_size - 1, 0))
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        length_function=len,
        keep_separator=True,
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
    )


async def split_into_chunks(text: str) -> list[str]:
    """把文档正文切成带长度约束的分块列表。"""
    normalized = text.strip()
    if not normalized:
        raise DocumentProcessingError("文档没有可切分的文本")

    segments = await _semantic_segments(normalized)
    splitter = _build_splitter()

    chunks: list[str] = []
    for segment in segments:
        for piece in splitter.split_text(segment):
            stripped = piece.strip()
            if stripped:
                chunks.append(stripped)

    chunks = _merge_short_chunks(chunks)
    if len(chunks) > settings.knowledge_base_max_chunks:
        logger.warning(
            "document_chunks_truncated",
            total=len(chunks),
            limit=settings.knowledge_base_max_chunks,
        )
        chunks = chunks[: settings.knowledge_base_max_chunks]
    if not chunks:
        raise DocumentProcessingError("文档切分后没有有效分块")
    return chunks


# ---------------------------------------------------------------------------
# 语义分割
# ---------------------------------------------------------------------------
async def _semantic_segments(text: str) -> list[str]:
    """按 LLM 给出的分割点把正文切成语义段；失败时返回整篇文本。"""
    paragraphs = _split_paragraphs(text)
    if len(text) < MIN_LLM_SPLIT_CHARS or len(paragraphs) < 3:
        return [text]

    points = await _ask_for_split_points(_build_prompt(paragraphs))
    offsets = _offsets_from_points(text, paragraphs, points)
    if not offsets:
        return [text]
    return _slice_by_offsets(text, offsets)


def _split_paragraphs(text: str) -> list[_Paragraph]:
    """优先按空行分段；PDF 等单行文本退化为按行分段。"""
    blocks = [
        _Paragraph(match.group().strip(), match.start())
        for match in re.finditer(r"[^\n]+(?:\n(?!\n)[^\n]*)*", text)
    ]
    blocks = [block for block in blocks if block.text]
    if len(blocks) >= 3:
        return blocks

    lines = [
        _Paragraph(match.group().strip(), match.start()) for match in re.finditer(r"[^\n]+", text)
    ]
    return [line for line in lines if line.text]


def _build_prompt(paragraphs: list[_Paragraph]) -> str:
    """拼装编号段落，按字符上限截断，避免超出模型上下文。"""
    lines: list[str] = []
    used = 0
    for index, paragraph in enumerate(paragraphs[:MAX_LLM_PARAGRAPHS], start=1):
        line = f"[{index}] {paragraph.text}"
        if used + len(line) > settings.knowledge_base_llm_split_max_chars:
            break
        lines.append(line)
        used += len(line) + 1
    return _USER_PROMPT_TEMPLATE.format(paragraphs="\n".join(lines))


async def _ask_for_split_points(prompt: str) -> list[int]:
    """调用 LLM 获取分割点；未配置或失败时返回空列表（走退化路径）。"""
    if not settings.deepseek_api_key:
        return []

    try:
        llm = _build_chat_model()
        response = await llm.ainvoke(
            [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
        content = _message_text(response.content)
        points = _parse_split_points(content)
        logger.info("document_split_points_detected", points=len(points))
        return points
    except Exception as exc:  # noqa: BLE001 - LLM 不可用时不应阻断文档入库
        logger.warning("document_split_points_failed", error=str(exc))
        return []


def _build_chat_model() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.deepseek_model,
        openai_api_key=settings.deepseek_api_key,
        openai_api_base=settings.deepseek_base_url,
        temperature=0,
        timeout=settings.deepseek_timeout_seconds,
        max_tokens=settings.deepseek_max_tokens,
        reasoning_effort=settings.deepseek_reasoning_effort,
    )


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text", "")))
        return "".join(parts)
    return str(content)


def _parse_split_points(raw: str) -> list[int]:
    """从模型回答中提取段落序号，容忍代码块与尾随逗号。"""
    data = _extract_json(raw)
    values: Any = data
    if isinstance(data, dict):
        for key in _SPLIT_KEYS:
            if key in data:
                values = data[key]
                break
        else:
            values = []

    if not isinstance(values, list):
        return []

    points: list[int] = []
    for item in values:
        if isinstance(item, dict):
            item = item.get("index") or item.get("paragraph") or item.get("序号")
        try:
            point = int(item)
        except (TypeError, ValueError):
            continue
        if point > 1:
            points.append(point)
    return sorted(set(points))


def _extract_json(raw: str) -> dict[str, Any] | list[Any] | None:
    text = raw.strip()
    candidates: list[str] = [text]
    candidates.extend(block.strip() for block in _JSON_FENCE.findall(text))
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            candidates.append(text[start : end + 1])

    for candidate in candidates:
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except (TypeError, ValueError):
            try:
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", candidate))
            except (TypeError, ValueError):
                continue
        if isinstance(data, (dict, list)):
            return data
    return None


def _offsets_from_points(
    text: str,
    paragraphs: list[_Paragraph],
    points: list[int],
) -> list[int]:
    """把段落序号映射为正文中的字符偏移，并按文档顺序去重。"""
    offsets: list[int] = []
    for point in points:
        if not 1 <= point <= len(paragraphs):
            continue
        offset = paragraphs[point - 1].start
        if 0 < offset < len(text):
            offsets.append(offset)
    return sorted(set(offsets))


def _slice_by_offsets(text: str, offsets: list[int]) -> list[str]:
    segments: list[str] = []
    previous = 0
    for offset in offsets:
        segments.append(text[previous:offset])
        previous = offset
    segments.append(text[previous:])
    return [segment for segment in segments if segment.strip()]


# ---------------------------------------------------------------------------
# 长度约束
# ---------------------------------------------------------------------------
def _merge_short_chunks(chunks: list[str]) -> list[str]:
    """把过短的分块尽量并入前一块，减少无意义的碎片。"""
    min_chars = settings.knowledge_base_min_chunk_chars
    max_chars = settings.knowledge_base_chunk_size
    merged: list[str] = []

    for chunk in chunks:
        if merged and len(chunk) < min_chars and len(merged[-1]) + len(chunk) <= max_chars:
            merged[-1] = f"{merged[-1]}\n{chunk}"
        else:
            merged.append(chunk)

    # 最后一块过短时优先并入前一块（允许略超目标长度）
    if len(merged) >= 2 and len(merged[-1]) < min_chars:
        tail = merged.pop()
        limit = max_chars + settings.knowledge_base_chunk_overlap
        if len(merged[-1]) + len(tail) <= limit:
            merged[-1] = f"{merged[-1]}\n{tail}"
        else:
            merged.append(tail)
    return merged
