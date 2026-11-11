"""简历筛选业务逻辑：文件解析、按 JD 的评分标准调用 Dify、保存与查询评分结果。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import aiofiles
import httpx
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import BACKEND_DIR, settings
from app.core.exceptions import (
    DifyInvalidParamError,
    DifyInvalidResponseError,
    NotFoundError,
    ScoringCriteriaRequiredError,
)
from app.core.logging import get_logger
from app.db.models import ResumeEvaluation, ScoringCriteria
from app.schemas.ai import ChatRequest, WorkflowType
from app.schemas.resume_evaluation import (
    EvaluationMetric,
    ResumeEvaluationListItem,
    ResumeEvaluationRead,
    ResumeStatus,
)
from app.services import (
    dify_service,
    jd_service,
    resume_parser_service,
    scoring_criteria_service,
)

logger = get_logger(__name__)

#: Dify query 的最大长度（app/schemas/ai.py）
_MAX_CRITERIA_CHARS = 100_000
_JSON_CODE_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_DEFAULT_MAX_SCORE = 100.0
_PLACEHOLDERS = {"none", "null", "n/a", "na", "未知", "不详", "--", "-"}
_METRIC_KEYS = (
    "evaluation_metrics",
    "metrics",
    "score_details",
    "dimensions",
    "scoring_dimensions",
    "评分维度",
    "评价维度",
    "评价指标",
)


@dataclass(slots=True)
class ParsedEvaluation:
    """从 AI 回答中解析出的结构化评分结果。"""

    total_score: float | None
    metrics: list[EvaluationMetric]
    candidate_name: str | None = None
    candidate_position: str | None = None
    candidate_age: int | None = None
    candidate_gender: str | None = None
    work_years: float | None = None
    education_level: str | None = None
    school: str | None = None


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
async def list_resume_evaluations(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    keyword: str | None = None,
    status: ResumeStatus | None = None,
    job_description_id: UUID | None = None,
) -> tuple[list[ResumeEvaluation], int]:
    """分页查询启用中的简历记录，按上传时间倒序。"""
    filters: list[ColumnElement[bool]] = [ResumeEvaluation.is_active.is_(True)]

    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        filters.append(
            or_(
                ResumeEvaluation.candidate_name.ilike(pattern),
                ResumeEvaluation.original_filename.ilike(pattern),
                ResumeEvaluation.candidate_position.ilike(pattern),
            )
        )
    if status is not None:
        filters.append(ResumeEvaluation.status == status.value)
    if job_description_id is not None:
        filters.append(ResumeEvaluation.job_description_id == job_description_id)

    total = await db.scalar(select(func.count()).select_from(ResumeEvaluation).where(*filters)) or 0
    stmt = (
        select(ResumeEvaluation)
        .where(*filters)
        .order_by(ResumeEvaluation.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.scalars(stmt)).all()
    return list(rows), total


async def get_resume_evaluation(db: AsyncSession, evaluation_id: UUID) -> ResumeEvaluation:
    """按 ID 获取启用中的简历记录，不存在时抛 404。"""
    record = await db.get(ResumeEvaluation, evaluation_id)
    if record is None or not record.is_active:
        raise NotFoundError("简历记录不存在", details={"resume_evaluation_id": str(evaluation_id)})
    return record


# ---------------------------------------------------------------------------
# 上传与评分
# ---------------------------------------------------------------------------
async def evaluate_resume(
    db: AsyncSession,
    *,
    filename: str,
    content: bytes,
    job_description_id: UUID,
    user_id: UUID,
    client: httpx.AsyncClient,
) -> ResumeEvaluation:
    """解析简历、调用 Dify type=3 评分并保存记录。

    评分前校验 JD 存在且 JD 下至少有一份启用中的评分标准；没有评分标准时
    直接抛 :class:`ScoringCriteriaRequiredError`，不调用 AI。
    """
    suffix = resume_parser_service.validate_resume(filename, len(content))
    jd = await jd_service.get_jd(db, job_description_id)
    criteria = await scoring_criteria_service.get_latest_for_jd(db, jd.id)
    if criteria is None:
        raise ScoringCriteriaRequiredError(
            details={"job_description_id": str(jd.id), "job_title": jd.title},
        )

    resume_text = await resume_parser_service.extract_resume_text(content, filename)
    request = build_evaluation_request(criteria, jd.title, resume_text)
    try:
        response = await dify_service.chat(request, user_id=user_id, client=client)
    except DifyInvalidParamError as exc:
        if "Structured output validation failed" in exc.message:
            raise DifyInvalidParamError(
                "Dify 简历评价节点启用了不兼容的结构化输出，请在 Dify 工作流中关闭 "
                "LLM 3 的结构化输出后重试",
                details=exc.details,
            ) from exc
        raise

    answer = response.answer.strip()
    if not answer:
        raise DifyInvalidResponseError("Dify 未返回简历评分内容")

    max_score = _parse_score(criteria.total_score) or _DEFAULT_MAX_SCORE
    parsed = parse_evaluation(answer)

    file_path = await _save_resume_file(content, suffix, user_id)
    record = ResumeEvaluation(
        original_filename=Path(filename).name[:255],
        file_path=str(file_path),
        file_type=suffix.lstrip("."),
        file_size=len(content),
        resume_content=resume_text,
        candidate_name=_truncate(parsed.candidate_name, 100),
        candidate_position=_truncate(parsed.candidate_position, 200),
        candidate_age=parsed.candidate_age,
        candidate_gender=_truncate(parsed.candidate_gender, 10),
        work_years=parsed.work_years,
        education_level=_truncate(parsed.education_level, 100),
        school=_truncate(parsed.school, 200),
        total_score=parsed.total_score,
        max_score=max_score,
        evaluation_metrics=[metric.model_dump() for metric in parsed.metrics],
        ai_answer=answer,
        ai_response=response.model_dump(mode="json"),
        status=ResumeStatus.PENDING.value,
        job_title=jd.title,
        job_description_id=jd.id,
        scoring_criteria_id=criteria.id,
        scoring_criteria_title=criteria.title,
        conversation_id=response.conversation_id or None,
        created_by=user_id,
        updated_by=user_id,
    )

    try:
        db.add(record)
        await db.commit()
        await db.refresh(record)
    except Exception:
        file_path.unlink(missing_ok=True)
        raise

    logger.info(
        "resume_evaluated",
        resume_evaluation_id=str(record.id),
        user_id=str(user_id),
        job_description_id=str(jd.id),
        scoring_criteria_id=str(criteria.id),
        content_chars=len(resume_text),
        total_score=record.total_score,
    )
    return record


def build_evaluation_request(
    criteria: ScoringCriteria,
    job_title: str,
    resume_text: str,
) -> ChatRequest:
    """组装 Dify type=3 请求：query 为评分标准，jianli 为简历正文。"""
    return ChatRequest(
        type=WorkflowType.RESUME_EVALUATION,
        query=criteria.content[:_MAX_CRITERIA_CHARS],
        inputs={
            "jianli": resume_text,
            "jobName": job_title[:48],
        },
        auto_generate_name=False,
    )


async def update_resume_status(
    db: AsyncSession,
    evaluation_id: UUID,
    status: ResumeStatus,
    *,
    user_id: UUID,
) -> ResumeEvaluation:
    """更新人工复核状态。"""
    record = await get_resume_evaluation(db, evaluation_id)
    record.status = status.value
    record.updated_by = user_id
    await db.commit()
    await db.refresh(record)
    logger.info(
        "resume_status_updated",
        resume_evaluation_id=str(record.id),
        status=status.value,
        user_id=str(user_id),
    )
    return record


# ---------------------------------------------------------------------------
# 模型转换
# ---------------------------------------------------------------------------
def to_list_item(record: ResumeEvaluation) -> ResumeEvaluationListItem:
    """把 ORM 记录转换成列表项。"""
    return ResumeEvaluationListItem(
        id=record.id,
        original_filename=record.original_filename,
        file_type=record.file_type,
        file_size=record.file_size,
        candidate_name=record.candidate_name,
        candidate_position=record.candidate_position,
        work_years=record.work_years,
        education_level=record.education_level,
        total_score=record.total_score,
        max_score=record.max_score,
        metric_count=len(record.evaluation_metrics or []),
        status=ResumeStatus(record.status),
        job_title=record.job_title,
        job_description_id=record.job_description_id,
        scoring_criteria_id=record.scoring_criteria_id,
        scoring_criteria_title=record.scoring_criteria_title,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def to_read(record: ResumeEvaluation) -> ResumeEvaluationRead:
    """把 ORM 记录转换成详情响应，并补齐评分维度数量。"""
    return ResumeEvaluationRead.model_validate(record).model_copy(
        update={"metric_count": len(record.evaluation_metrics or [])}
    )


# ---------------------------------------------------------------------------
# 文件保存
# ---------------------------------------------------------------------------
def _upload_directory() -> Path:
    root = Path(settings.resume_upload_dir)
    if not root.is_absolute():
        root = BACKEND_DIR / root
    return root


async def _save_resume_file(content: bytes, suffix: str, user_id: UUID) -> Path:
    directory = _upload_directory() / str(user_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid4().hex}{suffix}"
    async with aiofiles.open(path, "wb") as handle:
        await handle.write(content)
    return path


# ---------------------------------------------------------------------------
# AI 响应解析
# ---------------------------------------------------------------------------
def parse_evaluation(answer: str) -> ParsedEvaluation:
    """尽量从 AI 回答中解析 JSON；解析失败时保留原文，不伪造评分。"""
    data = _extract_json(answer)
    if isinstance(data, list):
        metrics = _parse_metrics(data)
        total = _sum_metrics(metrics)
        return ParsedEvaluation(total_score=total, metrics=metrics)

    payload = data if isinstance(data, dict) else {}
    # 兼容部分工作流把结果包在 data / result 下
    if not _first_present(payload, _METRIC_KEYS):
        for wrapper in ("data", "result"):
            nested = payload.get(wrapper)
            if isinstance(nested, dict):
                payload = nested
                break

    metrics = _parse_metrics(_first_present(payload, _METRIC_KEYS))
    total = _to_float(_first_present(payload, ("total_score", "totalScore", "总分", "score")))
    if total is None:
        total = _sum_metrics(metrics)

    return ParsedEvaluation(
        total_score=total,
        metrics=metrics,
        candidate_name=_clean_text(
            _first_present(
                payload,
                ("name", "candidate_name", "candidateName", "姓名", "候选人姓名"),
            )
        ),
        candidate_position=_clean_text(
            _first_present(
                payload,
                (
                    "position",
                    "candidate_position",
                    "candidatePosition",
                    "应聘岗位",
                    "岗位",
                    "职位",
                ),
            )
        ),
        candidate_age=_positive_int(_first_present(payload, ("age", "年龄"))),
        candidate_gender=_clean_text(_first_present(payload, ("sex", "gender", "性别"))),
        work_years=_parse_work_years(
            _first_present(
                payload,
                ("workYears", "work_years", "work_experience", "工作年限", "工作经验"),
            )
        ),
        education_level=_clean_text(
            _first_present(
                payload,
                ("education", "education_level", "educationLevel", "教育水平", "学历"),
            )
        ),
        school=_clean_text(
            _first_present(payload, ("school", "毕业院校", "毕业学校", "院校", "学校"))
        ),
    )


def _extract_json(answer: str) -> dict[str, Any] | list[Any] | None:
    text = answer.strip()
    candidates: list[str] = [text]
    candidates.extend(block.strip() for block in _JSON_CODE_BLOCK.findall(text))
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
            # 模型偶尔会输出尾随逗号，做一次轻量修复后重试
            try:
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", candidate))
            except (TypeError, ValueError):
                continue
        if isinstance(data, (dict, list)):
            return data
    return None


def _parse_metrics(value: Any) -> list[EvaluationMetric]:
    if not isinstance(value, list):
        return []
    metrics: list[EvaluationMetric] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _clean_text(_first_present(item, ("name", "评价指标", "指标", "dimension", "维度")))
        if not name:
            continue
        metrics.append(
            EvaluationMetric(
                name=name,
                score=_to_float(_first_present(item, ("score", "得分", "分值"))) or 0.0,
                max=_to_float(_first_present(item, ("max", "max_score", "满分"))) or 0.0,
                reason=_clean_text(
                    _first_present(item, ("reason", "评分理由", "理由", "comment", "说明"))
                )
                or "",
            )
        )
    return metrics


def _sum_metrics(metrics: list[EvaluationMetric]) -> float | None:
    return round(sum(metric.score for metric in metrics), 2) if metrics else None


def _first_present(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in _PLACEHOLDERS:
        return None
    return text


def _truncate(value: str | None, max_length: int) -> str | None:
    if value is None:
        return None
    return value[:max_length]


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
        if match:
            try:
                return float(match.group())
            except ValueError:
                return None
    return None


def _positive_int(value: Any) -> int | None:
    number = _to_float(value)
    if number is None or number <= 0:
        return None
    return int(number)


def _parse_score(value: str | None) -> float | None:
    number = _to_float(value)
    return number if number and number > 0 else None


def _parse_work_years(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if not text or text in _PLACEHOLDERS:
        return None
    if "应届" in text or "fresh" in text:
        return 0.0
    match = re.search(r"(\d+(?:\.\d+)?)\s*[\-~–—至]\s*(\d+(?:\.\d+)?)", text)
    if match:
        return round((float(match.group(1)) + float(match.group(2))) / 2, 1)
    return _to_float(text)
