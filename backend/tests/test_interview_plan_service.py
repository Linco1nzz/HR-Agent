"""智能面试服务测试：请求组装、流式生成、保存 / 编辑与列表展示。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from app.core.exceptions import NotFoundError
from app.db.models import InterviewPlan, JobDescription, ResumeEvaluation
from app.schemas.ai import WorkflowType
from app.schemas.interview_plan import (
    GenerateInterviewPlanRequest,
    InterviewPlanCreate,
    InterviewPlanUpdate,
)
from app.services import (
    dify_service,
    interview_plan_service,
    jd_service,
    resume_evaluation_service,
)


def make_jd(**overrides: Any) -> JobDescription:
    now = datetime.now(UTC)
    data: dict[str, Any] = {
        "id": uuid4(),
        "title": "高级前端工程师",
        "department": "技术部",
        "location": "上海",
        "experience_level": "5 年以上",
        "education": "本科",
        "skills": ["Vue 3", "TypeScript"],
        "content": "# 岗位职责\n负责中后台前端架构与业务开发",
        "requirements": "有大型项目经验",
        "status": "published",
        "workflow_type": "jd_generation",
        "created_at": now,
        "updated_at": now,
        "is_active": True,
    }
    data.update(overrides)
    return JobDescription(**data)


def make_evaluation(jd: JobDescription, **overrides: Any) -> ResumeEvaluation:
    now = datetime.now(UTC)
    data: dict[str, Any] = {
        "id": uuid4(),
        "original_filename": "张三-前端.txt",
        "file_type": "txt",
        "file_size": 128,
        "resume_content": "张三，5 年前端经验，熟悉 Vue 3 和 TypeScript。",
        "candidate_name": "张三",
        "candidate_position": "高级前端工程师",
        "work_years": 5.0,
        "education_level": "本科",
        "total_score": 88.0,
        "max_score": 100.0,
        "evaluation_metrics": [],
        "status": "pending",
        "job_title": jd.title,
        "job_description_id": jd.id,
        "scoring_criteria_id": uuid4(),
        "created_at": now,
        "updated_at": now,
        "is_active": True,
    }
    data.update(overrides)
    return ResumeEvaluation(**data)


def make_plan(**overrides: Any) -> InterviewPlan:
    now = datetime.now(UTC)
    data: dict[str, Any] = {
        "id": uuid4(),
        "candidate_name": "张三",
        "candidate_position": "高级前端工程师",
        "content": "# 张三面试方案\n\n## 一、考察重点\n- 架构能力",
        "resume_evaluation_id": uuid4(),
        "job_title": "高级前端工程师",
        "job_description_id": uuid4(),
        "conversation_id": "conv-4",
        "workflow_type": "interview_plan",
        "created_at": now,
        "updated_at": now,
        "is_active": True,
    }
    data.update(overrides)
    return InterviewPlan(**data)


class FakeScalarResult:
    def __init__(self, rows: list[InterviewPlan]) -> None:
        self._rows = rows

    def all(self) -> list[InterviewPlan]:
        return self._rows


class FakeSession:
    """只实现面试服务用到的 AsyncSession 子集。"""

    def __init__(
        self,
        *,
        plan: InterviewPlan | None = None,
        plans: list[InterviewPlan] | None = None,
        total: int = 0,
    ) -> None:
        self.plan = plan
        self.plans = plans or []
        self.total = total
        self.added: InterviewPlan | None = None
        self.commit_count = 0
        self.refresh_count = 0
        self.now = datetime.now(UTC)

    async def get(self, model: type[Any], record_id: UUID) -> Any:
        if model is InterviewPlan and self.plan is not None and self.plan.id == record_id:
            return self.plan
        return None

    async def scalar(self, statement: Any) -> int:  # noqa: ARG002
        return self.total

    async def scalars(self, statement: Any) -> FakeScalarResult:  # noqa: ARG002
        return FakeScalarResult(self.plans)

    def add(self, record: InterviewPlan) -> None:
        self.added = record
        record.id = uuid4()
        record.created_at = self.now
        record.updated_at = self.now

    async def commit(self) -> None:
        self.commit_count += 1

    async def refresh(self, record: InterviewPlan) -> None:  # noqa: ARG002
        self.refresh_count += 1


def test_build_generation_request_uses_jd_and_resume() -> None:
    jd = make_jd()
    evaluation = make_evaluation(jd)

    request = interview_plan_service.build_generation_request(
        evaluation,
        jd,
        "重点考察架构能力",
    )

    assert request.type == WorkflowType.INTERVIEW_PLAN
    assert request.query == "重点考察架构能力"
    assert evaluation.resume_content in request.inputs["jianli"]
    assert "高级前端工程师" in request.inputs["jd"]
    assert "负责中后台前端架构" in request.inputs["jd"]
    assert "有大型项目经验" in request.inputs["jd"]
    assert "Vue 3、TypeScript" in request.inputs["jd"]


def test_build_generation_request_truncates_long_inputs() -> None:
    jd = make_jd(content="甲" * 60_000)
    evaluation = make_evaluation(jd, resume_content="乙" * 100_000)

    request = interview_plan_service.build_generation_request(evaluation, jd)

    assert request.query == ""
    assert len(request.inputs["jd"]) == 48_000
    assert len(request.inputs["jianli"]) == 80_000


def test_summarize_jd_omits_missing_optional_fields() -> None:
    jd = make_jd(department=None, location=None, experience_level=None, education=None, skills=None)

    summary = interview_plan_service.summarize_jd(jd)

    assert "所属部门" not in summary
    assert "技能要求" not in summary
    assert "职位描述：" in summary


async def test_stream_generate_interview_plan_emits_done_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jd = make_jd()
    evaluation = make_evaluation(jd)
    captured: dict[str, Any] = {}

    async def fake_get_evaluation(_db: Any, evaluation_id: UUID) -> ResumeEvaluation:
        assert evaluation_id == evaluation.id
        return evaluation

    async def fake_get_jd(_db: Any, jd_id: UUID) -> JobDescription:
        assert jd_id == jd.id
        return jd

    async def fake_iter_events(
        request: Any,
        *,
        user_id: UUID | str,
        client: httpx.AsyncClient | None = None,
    ) -> Any:
        captured["request"] = request
        captured["user_id"] = user_id
        yield {"event": "message", "answer": "# 张三面试方案\n"}
        yield {"event": "message", "answer": "## 一、考察重点\n- 架构能力"}
        yield {
            "event": "message_end",
            "metadata": {"usage": {"total_tokens": 128}},
            "conversation_id": "conv-4",
            "task_id": "task-4",
        }
        yield {"event": "workflow_finished", "data": {"outputs": {}}}

    monkeypatch.setattr(resume_evaluation_service, "get_resume_evaluation", fake_get_evaluation)
    monkeypatch.setattr(jd_service, "get_jd", fake_get_jd)
    monkeypatch.setattr(dify_service, "iter_stream_events", fake_iter_events)

    user_id = uuid4()
    stream = await interview_plan_service.stream_generate_interview_plan(
        FakeSession(),  # type: ignore[arg-type]
        GenerateInterviewPlanRequest(resume_evaluation_id=evaluation.id),
        user_id=user_id,
        client=httpx.AsyncClient(),
    )
    chunks = [chunk async for chunk in stream]

    text = b"".join(chunks).decode()
    assert "event: start" in text
    assert "event: delta" in text
    assert "event: done" in text
    done = next(
        json.loads(frame.split("data: ", 1)[1])
        for frame in text.split("\n\n")
        if frame.startswith("event: done")
    )
    assert done["content"] == "# 张三面试方案\n## 一、考察重点\n- 架构能力"
    assert done["candidate_name"] == "张三"
    assert done["candidate_position"] == "高级前端工程师"
    assert done["resume_evaluation_id"] == str(evaluation.id)
    assert done["job_title"] == jd.title
    assert done["conversation_id"] == "conv-4"

    request = captured["request"]
    assert request.type == WorkflowType.INTERVIEW_PLAN
    assert request.inputs["jianli"] == evaluation.resume_content
    assert captured["user_id"] == user_id


async def test_stream_generate_interview_plan_uses_real_dify_sse_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jd = make_jd()
    evaluation = make_evaluation(jd)
    captured: dict[str, Any] = {}

    async def fake_get_evaluation(_db: Any, _evaluation_id: UUID) -> ResumeEvaluation:
        return evaluation

    async def fake_get_jd(_db: Any, _jd_id: UUID) -> JobDescription:
        return jd

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        sse = (
            'data: {"event":"message","answer":"# 张三面试方案\\n",'
            '"conversation_id":"conv-4","task_id":"task-4"}\n\n'
            'data: {"event":"message","answer":"## 一、考察重点\\n- 架构能力"}\n\n'
            'data: {"event":"message_end","metadata":{"usage":{"total_tokens":42}}}\n\n'
            'data: {"event":"workflow_finished","data":{"outputs":{}}}\n\n'
        )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse.encode(),
        )

    monkeypatch.setattr(resume_evaluation_service, "get_resume_evaluation", fake_get_evaluation)
    monkeypatch.setattr(jd_service, "get_jd", fake_get_jd)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        stream = await interview_plan_service.stream_generate_interview_plan(
            FakeSession(),  # type: ignore[arg-type]
            GenerateInterviewPlanRequest(resume_evaluation_id=evaluation.id),
            user_id=uuid4(),
            client=http_client,
        )
        chunks = [chunk async for chunk in stream]

    text = b"".join(chunks).decode()
    done = next(
        json.loads(frame.split("data: ", 1)[1])
        for frame in text.split("\n\n")
        if frame.startswith("event: done")
    )
    assert done["content"] == "# 张三面试方案\n## 一、考察重点\n- 架构能力"
    assert done["candidate_name"] == "张三"
    assert done["job_title"] == jd.title

    body = captured["body"]
    assert body["inputs"]["type"] == 4
    assert body["inputs"]["jianli"] == evaluation.resume_content
    assert "高级前端工程师" in body["inputs"]["jd"]
    assert body["query"] == "请根据 JD 和简历生成面试方案与面试题"


async def test_stream_generate_requires_existing_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_evaluation(_db: Any, _evaluation_id: UUID) -> ResumeEvaluation:
        raise NotFoundError("简历记录不存在")

    monkeypatch.setattr(resume_evaluation_service, "get_resume_evaluation", fake_get_evaluation)

    with pytest.raises(NotFoundError):
        await interview_plan_service.stream_generate_interview_plan(
            FakeSession(),  # type: ignore[arg-type]
            GenerateInterviewPlanRequest(resume_evaluation_id=uuid4()),
            user_id=uuid4(),
            client=httpx.AsyncClient(),
        )


async def test_create_interview_plan_snapshots_jd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jd = make_jd()
    evaluation = make_evaluation(jd)
    db = FakeSession()
    user_id = uuid4()

    async def fake_get_evaluation(_db: Any, evaluation_id: UUID) -> ResumeEvaluation:
        assert evaluation_id == evaluation.id
        return evaluation

    monkeypatch.setattr(resume_evaluation_service, "get_resume_evaluation", fake_get_evaluation)

    record = await interview_plan_service.create_interview_plan(
        db,  # type: ignore[arg-type]
        InterviewPlanCreate(
            candidate_name="张三",
            candidate_position="高级前端工程师",
            content="# 面试方案\n- 架构能力",
            resume_evaluation_id=evaluation.id,
            conversation_id="conv-4",
        ),
        user_id=user_id,
    )

    assert db.added is record
    assert db.commit_count == 1
    assert record.resume_evaluation_id == evaluation.id
    assert record.job_title == jd.title
    assert record.job_description_id == jd.id
    assert record.workflow_type == "interview_plan"
    assert record.created_by == user_id


async def test_update_interview_plan_content() -> None:
    plan = make_plan()
    db = FakeSession(plan=plan)

    updated = await interview_plan_service.update_interview_plan(
        db,  # type: ignore[arg-type]
        plan.id,
        InterviewPlanUpdate(content="# 新方案\n- 团队协作"),
        user_id=uuid4(),
    )

    assert updated.content == "# 新方案\n- 团队协作"
    assert db.commit_count == 1


async def test_list_interview_plans_returns_records() -> None:
    plan = make_plan()
    db = FakeSession(plans=[plan], total=1)

    records, total = await interview_plan_service.list_interview_plans(
        db,  # type: ignore[arg-type]
        page=1,
        page_size=10,
        resume_evaluation_id=plan.resume_evaluation_id,
        keyword="张三",
    )

    assert records == [plan]
    assert total == 1


def test_to_list_item_builds_markdown_preview() -> None:
    plan = make_plan(
        content="# 张三面试方案\n\n## 一、考察重点\n- **架构能力**\n- 团队协作",
    )

    item = interview_plan_service.to_list_item(plan)

    assert item.candidate_name == "张三"
    assert "架构能力" in item.content_preview
    assert "#" not in item.content_preview
    assert item.content_preview.startswith("面试方案")
