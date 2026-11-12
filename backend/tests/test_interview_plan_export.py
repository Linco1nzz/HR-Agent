"""面试方案导出测试：Markdown 内容、Word 文件与下载文件名。"""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from uuid import uuid4

from docx import Document

from app.db.models import InterviewPlan
from app.schemas.interview_plan import ExportFormat
from app.services import interview_plan_export


def make_plan(**overrides: object) -> InterviewPlan:
    now = datetime(2026, 11, 11, 5, 30, tzinfo=UTC)
    data: dict[str, object] = {
        "id": uuid4(),
        "candidate_name": "张三",
        "candidate_position": "高级前端工程师",
        "content": (
            "# 面试方案\n\n"
            "## 一、考察重点\n"
            "- **架构能力**：关注 Vue 3 工程化\n"
            "- 团队协作\n\n"
            "1. 请介绍一次性能优化\n"
            "2. 如何设计组件库\n\n"
            "> 提示：结合项目追问\n"
        ),
        "resume_evaluation_id": uuid4(),
        "job_title": "高级前端工程师",
        "job_description_id": uuid4(),
        "created_at": now,
        "updated_at": now,
        "is_active": True,
    }
    data.update(overrides)
    return InterviewPlan(**data)


def test_build_markdown_includes_metadata_and_content() -> None:
    plan = make_plan()

    markdown = interview_plan_export.build_markdown(plan)

    assert markdown.startswith("# 张三 面试方案")
    assert "- 应聘岗位：高级前端工程师" in markdown
    assert "- 关联 JD：高级前端工程师" in markdown
    assert "## 一、考察重点" in markdown
    assert markdown.endswith("\n")


def test_build_markdown_omits_missing_job_title() -> None:
    plan = make_plan(job_title=None)

    markdown = interview_plan_export.build_markdown(plan)

    assert "关联 JD" not in markdown


def test_build_docx_returns_word_document() -> None:
    plan = make_plan()

    content = interview_plan_export.build_docx(plan)

    assert content.startswith(b"PK")
    assert len(content) > 10_000


def test_build_docx_renders_markdown_table() -> None:
    plan = make_plan(
        content=(
            "# 面试方案\n\n"
            "| 序号 | 面试题 | 考察点 |\n"
            "| --- | --- | --- |\n"
            "| 1 | 介绍一次性能优化 | 性能意识 |\n"
            "| 2 | 如何设计组件库 | 架构能力 |\n"
        )
    )

    content = interview_plan_export.build_docx(plan)
    document = Document(BytesIO(content))

    assert len(document.tables) == 1
    table = document.tables[0]
    assert table.rows[0].cells[0].text == "序号"
    assert table.rows[1].cells[1].text == "介绍一次性能优化"
    assert table.rows[2].cells[2].text == "架构能力"


def test_build_filename_uses_candidate_and_date() -> None:
    plan = make_plan()

    assert (
        interview_plan_export.build_filename(plan, ExportFormat.DOCX)
        == "面试方案-张三-20261111.docx"
    )
    assert (
        interview_plan_export.build_filename(plan, ExportFormat.MARKDOWN)
        == "面试方案-张三-20261111.md"
    )


def test_build_filename_sanitizes_illegal_characters() -> None:
    plan = make_plan(candidate_name='张/三:*?"<>|')

    filename = interview_plan_export.build_filename(plan, ExportFormat.DOCX)

    assert "/" not in filename
    assert "*" not in filename
    assert filename.startswith("面试方案-张_三")


def test_content_disposition_encodes_chinese_filename() -> None:
    header = interview_plan_export.content_disposition("面试方案-张三-20261111.docx")

    assert header.startswith("attachment;")
    assert 'filename="interview-plan.docx"' in header
    assert "filename*=UTF-8''" in header
    assert "%E9%9D%A2%E8%AF%95%E6%96%B9%E6%A1%88" in header
