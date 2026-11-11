"""简历评分服务测试：评分标准校验、Dify 调用、结果解析与落库。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from app.core.config import settings
from app.core.exceptions import (
    DifyInvalidParamError,
    NotFoundError,
    ScoringCriteriaRequiredError,
    UnsupportedResumeFormatError,
)
from app.db.models import JobDescription, ResumeEvaluation, ScoringCriteria
from app.schemas.ai import ChatResponse, ChatUsage, WorkflowType
from app.schemas.resume_evaluation import ResumeStatus
from app.services import (
    dify_service,
    resume_evaluation_service,
    scoring_criteria_service,
)


def make_jd_record(**overrides: Any) -> JobDescription:
    now = datetime.now(UTC)
    data: dict[str, Any] = {
        "id": uuid4(),
        "title": "高级前端工程师",
        "content": "# 岗位职责\n负责前端架构与业务开发",
        "requirements": "有大型中后台项目经验",
        "status": "published",
        "workflow_type": "jd_generation",
        "created_at": now,
        "updated_at": now,
        "is_active": True,
    }
    data.update(overrides)
    return JobDescription(**data)


def make_criteria_record(jd_id: UUID, **overrides: Any) -> ScoringCriteria:
    now = datetime.now(UTC)
    data: dict[str, Any] = {
        "id": uuid4(),
        "title": "高级前端工程师 - 简历评分标准",
        "job_title": "高级前端工程师",
        "content": "# 评分标准\n- 专业技能 40 分\n- 项目经验 30 分",
        "total_score": "100",
        "status": "generated",
        "workflow_type": "scoring_criteria_generation",
        "job_description_id": jd_id,
        "created_at": now,
        "updated_at": now,
        "is_active": True,
    }
    data.update(overrides)
    return ScoringCriteria(**data)


def make_resume_record(**overrides: Any) -> ResumeEvaluation:
    now = datetime.now(UTC)
    data: dict[str, Any] = {
        "id": uuid4(),
        "original_filename": "resume.txt",
        "file_type": "txt",
        "file_size": 128,
        "resume_content": "张三，5 年前端经验",
        "candidate_name": "张三",
        "candidate_position": "高级前端工程师",
        "work_years": 5.0,
        "education_level": "本科",
        "total_score": 88.0,
        "max_score": 100.0,
        "evaluation_metrics": [
            {"name": "专业技能", "score": 35, "max": 40, "reason": "Vue 3 经验丰富"},
            {"name": "项目经验", "score": 28, "max": 30, "reason": "有中后台项目经验"},
        ],
        "status": "pending",
        "job_title": "高级前端工程师",
        "job_description_id": uuid4(),
        "scoring_criteria_id": uuid4(),
        "scoring_criteria_title": "高级前端工程师 - 简历评分标准",
        "created_at": now,
        "updated_at": now,
        "is_active": True,
    }
    data.update(overrides)
    return ResumeEvaluation(**data)


class FakeScalarResult:
    def __init__(self, rows: list[ResumeEvaluation]) -> None:
        self._rows = rows

    def all(self) -> list[ResumeEvaluation]:
        return self._rows


class FakeSession:
    """只实现简历服务用到的 AsyncSession 子集。"""

    def __init__(
        self,
        *,
        jd: JobDescription | None = None,
        record: ResumeEvaluation | None = None,
        records: list[ResumeEvaluation] | None = None,
        total: int = 0,
    ) -> None:
        self.jd = jd
        self.record = record
        self.records = records or []
        self.total = total
        self.added: ResumeEvaluation | None = None
        self.commit_count = 0
        self.refresh_count = 0
        self.now = datetime.now(UTC)

    async def get(self, model: type[Any], record_id: UUID) -> Any:
        if model is JobDescription:
            return self.jd if self.jd is not None and self.jd.id == record_id else None
        if model is ResumeEvaluation:
            return self.record if self.record is not None and self.record.id == record_id else None
        return None

    async def scalar(self, statement: Any) -> int:  # noqa: ARG002
        return self.total

    async def scalars(self, statement: Any) -> FakeScalarResult:  # noqa: ARG002
        return FakeScalarResult(self.records)

    def add(self, record: ResumeEvaluation) -> None:
        self.added = record
        record.id = uuid4()
        record.created_at = self.now
        record.updated_at = self.now

    async def commit(self) -> None:
        self.commit_count += 1

    async def refresh(self, record: ResumeEvaluation) -> None:
        self.refresh_count += 1


def make_chat_response(answer: str) -> ChatResponse:
    return ChatResponse(
        type=WorkflowType.RESUME_EVALUATION,
        answer=answer,
        conversation_id="conv-3",
        task_id="task-3",
        usage=ChatUsage(total_tokens=256),
    )


async def test_evaluate_resume_saves_parsed_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    jd = make_jd_record()
    criteria = make_criteria_record(jd.id)
    db = FakeSession(jd=jd)
    captured: dict[str, Any] = {}
    answer = """
    {
      "evaluation_metrics": [
        {"name": "专业技能", "score": 35, "max": 40, "reason": "Vue 3 经验丰富"},
        {"name": "项目经验", "score": 28, "max": 30, "reason": "有中后台项目经验"}
      ],
      "total_score": 88,
      "name": "张三",
      "position": "高级前端工程师",
      "workYears": "5年",
      "education": "本科",
      "age": 28,
      "sex": "男",
      "school": "上海理工大学"
    }
    """

    async def fake_criteria(_db: Any, _jd_id: UUID) -> ScoringCriteria | None:
        return criteria

    async def fake_chat(
        request: Any,
        *,
        user_id: UUID | str,
        client: httpx.AsyncClient | None = None,
    ) -> ChatResponse:
        captured["request"] = request
        captured["user_id"] = user_id
        return make_chat_response(answer)

    monkeypatch.setattr(scoring_criteria_service, "get_latest_for_jd", fake_criteria)
    monkeypatch.setattr(dify_service, "chat", fake_chat)
    monkeypatch.setattr(settings, "resume_upload_dir", str(tmp_path))

    record = await resume_evaluation_service.evaluate_resume(
        db,  # type: ignore[arg-type]
        filename="张三-前端.txt",
        content="张三，5 年前端经验，熟悉 Vue 3 和 TypeScript。".encode(),
        job_description_id=jd.id,
        user_id=uuid4(),
        client=httpx.AsyncClient(),
    )

    assert db.added is record
    assert db.commit_count == 1
    assert record.candidate_name == "张三"
    assert record.candidate_position == "高级前端工程师"
    assert record.candidate_age == 28
    assert record.candidate_gender == "男"
    assert record.work_years == 5.0
    assert record.education_level == "本科"
    assert record.school == "上海理工大学"
    assert record.total_score == 88.0
    assert record.max_score == 100.0
    assert record.status == "pending"
    assert len(record.evaluation_metrics or []) == 2
    assert record.ai_answer is not None
    assert record.ai_response is not None
    assert record.job_description_id == jd.id
    assert record.scoring_criteria_id == criteria.id
    assert record.file_type == "txt"
    assert record.file_size > 0
    assert record.file_path is not None
    assert Path(record.file_path).exists()

    request = captured["request"]
    assert request.type == WorkflowType.RESUME_EVALUATION
    assert request.query == criteria.content
    assert request.inputs["jianli"] == "张三，5 年前端经验，熟悉 Vue 3 和 TypeScript。"
    assert request.inputs["jobName"] == "高级前端工程师"


async def test_evaluate_resume_requires_scoring_criteria(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    jd = make_jd_record()
    db = FakeSession(jd=jd)
    called = False

    async def fake_criteria(_db: Any, _jd_id: UUID) -> None:
        return None

    async def fake_chat(*args: Any, **kwargs: Any) -> ChatResponse:
        nonlocal called
        called = True
        return make_chat_response("{}")

    monkeypatch.setattr(scoring_criteria_service, "get_latest_for_jd", fake_criteria)
    monkeypatch.setattr(dify_service, "chat", fake_chat)
    monkeypatch.setattr(settings, "resume_upload_dir", str(tmp_path))

    with pytest.raises(ScoringCriteriaRequiredError):
        await resume_evaluation_service.evaluate_resume(
            db,  # type: ignore[arg-type]
            filename="resume.txt",
            content=b"resume",
            job_description_id=jd.id,
            user_id=uuid4(),
            client=httpx.AsyncClient(),
        )

    assert called is False


async def test_evaluate_resume_maps_structured_output_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    jd = make_jd_record()
    criteria = make_criteria_record(jd.id)

    async def fake_criteria(_db: Any, _jd_id: UUID) -> ScoringCriteria:
        return criteria

    async def fake_chat(
        request: Any,
        *,
        user_id: UUID | str,
        client: httpx.AsyncClient | None = None,
    ) -> ChatResponse:
        raise DifyInvalidParamError(
            "Run failed: Structured output validation failed (stage=result, path=$)"
        )

    monkeypatch.setattr(scoring_criteria_service, "get_latest_for_jd", fake_criteria)
    monkeypatch.setattr(dify_service, "chat", fake_chat)
    monkeypatch.setattr(settings, "resume_upload_dir", str(tmp_path))

    with pytest.raises(DifyInvalidParamError) as exc_info:
        await resume_evaluation_service.evaluate_resume(
            FakeSession(jd=jd),  # type: ignore[arg-type]
            filename="resume.txt",
            content=b"resume",
            job_description_id=jd.id,
            user_id=uuid4(),
            client=httpx.AsyncClient(),
        )

    assert "关闭" in exc_info.value.message
    assert "LLM 3" in exc_info.value.message


async def test_evaluate_resume_requires_existing_jd() -> None:
    with pytest.raises(NotFoundError):
        await resume_evaluation_service.evaluate_resume(
            FakeSession(),  # type: ignore[arg-type]
            filename="resume.txt",
            content=b"resume",
            job_description_id=uuid4(),
            user_id=uuid4(),
            client=httpx.AsyncClient(),
        )


async def test_evaluate_resume_rejects_unsupported_format() -> None:
    with pytest.raises(UnsupportedResumeFormatError):
        await resume_evaluation_service.evaluate_resume(
            FakeSession(),  # type: ignore[arg-type]
            filename="resume.zip",
            content=b"zip",
            job_description_id=uuid4(),
            user_id=uuid4(),
            client=httpx.AsyncClient(),
        )


def test_parse_evaluation_handles_fenced_json_and_aliases() -> None:
    answer = """AI 评价如下：
```json
{
  "metrics": [
    {"评价指标": "专业技能", "得分": 35, "满分": 40, "评分理由": "Vue 3 经验丰富"}
  ],
  "totalScore": "85/100",
  "candidate_name": "李四",
  "工作年限": "3-5年",
  "学历": "本科",
  "性别": "女",
  "年龄": "30",
  "毕业院校": "复旦大学"
}
```
"""

    parsed = resume_evaluation_service.parse_evaluation(answer)

    assert parsed.total_score == 85.0
    assert parsed.metrics[0].name == "专业技能"
    assert parsed.metrics[0].score == 35.0
    assert parsed.metrics[0].max == 40.0
    assert parsed.candidate_name == "李四"
    assert parsed.work_years == 4.0
    assert parsed.education_level == "本科"
    assert parsed.candidate_gender == "女"
    assert parsed.candidate_age == 30
    assert parsed.school == "复旦大学"


def test_parse_evaluation_matches_dify_type3_contract() -> None:
    answer = (
        '{"evaluation_metrics": ['
        '{"name": "学历", "score": 15, "max": 20, "reason": "本科"}],'
        '"total_score": 85, "name": "张三", "position": "前端开发工程师",'
        '"workYears": "3", "教育水平": "本科", "年龄": 38, "sex": "男",'
        '"school": "上海理工大学"}'
    )

    parsed = resume_evaluation_service.parse_evaluation(answer)

    assert parsed.total_score == 85.0
    assert parsed.metrics[0].name == "学历"
    assert parsed.candidate_name == "张三"
    assert parsed.candidate_position == "前端开发工程师"
    assert parsed.work_years == 3.0
    assert parsed.education_level == "本科"
    assert parsed.candidate_age == 38
    assert parsed.candidate_gender == "男"
    assert parsed.school == "上海理工大学"


def test_parse_evaluation_repairs_trailing_comma() -> None:
    parsed = resume_evaluation_service.parse_evaluation(
        '{"evaluation_metrics": [{"name": "学历", "score": 15, "max": 20,}], "total_score": 85,}'
    )

    assert parsed.total_score == 85.0
    assert parsed.metrics[0].name == "学历"


def test_parse_evaluation_keeps_raw_answer_when_json_is_invalid() -> None:
    parsed = resume_evaluation_service.parse_evaluation("这是一段没有 JSON 的 AI 评价。")

    assert parsed.total_score is None
    assert parsed.metrics == []
    assert parsed.candidate_name is None


def test_parse_evaluation_handles_metric_list_root() -> None:
    parsed = resume_evaluation_service.parse_evaluation(
        '[{"name": "学历", "score": 15, "max": 20, "reason": "本科"}]'
    )

    assert parsed.total_score == 15.0
    assert parsed.metrics[0].name == "学历"


def test_build_evaluation_request_uses_criteria_query() -> None:
    jd = make_jd_record()
    criteria = make_criteria_record(jd.id)

    request = resume_evaluation_service.build_evaluation_request(
        criteria,
        jd.title,
        "候选人简历正文",
    )

    assert request.type == WorkflowType.RESUME_EVALUATION
    assert request.query == criteria.content
    assert request.inputs == {"jianli": "候选人简历正文", "jobName": jd.title}


async def test_list_resume_evaluations_returns_records() -> None:
    record = make_resume_record()
    db = FakeSession(records=[record], total=1)

    records, total = await resume_evaluation_service.list_resume_evaluations(
        db,  # type: ignore[arg-type]
        page=1,
        page_size=10,
        keyword="张三",
        status=ResumeStatus.PENDING,
    )

    assert records == [record]
    assert total == 1


async def test_update_resume_status() -> None:
    record = make_resume_record()
    db = FakeSession(record=record)

    updated = await resume_evaluation_service.update_resume_status(
        db,  # type: ignore[arg-type]
        record.id,
        ResumeStatus.INTERVIEW,
        user_id=uuid4(),
    )

    assert updated.status == ResumeStatus.INTERVIEW.value
    assert db.commit_count == 1


def test_to_list_item_and_read_include_metric_count() -> None:
    record = make_resume_record()

    item = resume_evaluation_service.to_list_item(record)
    detail = resume_evaluation_service.to_read(record)

    assert item.metric_count == 2
    assert item.status == ResumeStatus.PENDING
    assert detail.metric_count == 2
    assert detail.candidate_name == "张三"
    assert len(detail.evaluation_metrics) == 2
