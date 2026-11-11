"""简历筛选 / 评分相关的请求与响应模型。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

WORKFLOW_TYPE = "resume_evaluation"
SUPPORTED_RESUME_EXTENSIONS = (".pdf", ".doc", ".docx", ".txt")


class ResumeStatus(StrEnum):
    """简历复核状态。"""

    PENDING = "pending"
    INTERVIEW = "interview"
    REJECTED = "rejected"


class EvaluationMetric(BaseModel):
    """单个评分维度。"""

    name: str = Field(description="维度名称")
    score: float = Field(default=0, description="得分")
    max: float = Field(default=0, description="满分")
    reason: str = Field(default="", description="评分理由")

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("评分维度名称不能为空")
        return stripped


class ResumeEvaluationListItem(BaseModel):
    """简历列表项（不返回简历正文与评分明细）。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="简历记录 ID")
    original_filename: str = Field(description="原始文件名")
    file_type: str = Field(description="文件类型")
    file_size: int = Field(description="文件大小（字节）")
    candidate_name: str | None = Field(default=None, description="候选人姓名")
    candidate_position: str | None = Field(default=None, description="应聘岗位")
    work_years: float | None = Field(default=None, description="工作年限")
    education_level: str | None = Field(default=None, description="学历")
    total_score: float | None = Field(default=None, description="总分")
    max_score: float | None = Field(default=None, description="评分标准总分")
    metric_count: int = Field(default=0, description="评分维度数量")
    status: ResumeStatus = Field(description="复核状态")
    job_title: str | None = Field(default=None, description="JD 标题")
    job_description_id: UUID = Field(description="关联 JD ID")
    scoring_criteria_id: UUID = Field(description="评分标准 ID")
    scoring_criteria_title: str | None = Field(default=None, description="评分标准标题")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class ResumeEvaluationRead(ResumeEvaluationListItem):
    """简历详情（含完整正文与评分结果）。"""

    candidate_age: int | None = Field(default=None, description="年龄")
    candidate_gender: str | None = Field(default=None, description="性别")
    school: str | None = Field(default=None, description="毕业院校")
    resume_content: str = Field(description="解析后的简历文本")
    evaluation_metrics: list[EvaluationMetric] = Field(
        default_factory=list,
        description="评分维度列表",
    )
    ai_answer: str | None = Field(default=None, description="AI 原始评价")
    conversation_id: str | None = Field(default=None, description="Dify 会话 ID")
    created_by: UUID | None = Field(default=None, description="创建人 ID")


class ResumeEvaluationListResponse(BaseModel):
    """简历分页列表。"""

    items: list[ResumeEvaluationListItem] = Field(default_factory=list, description="简历列表")
    total: int = Field(description="总数")
    page: int = Field(description="当前页")
    page_size: int = Field(description="每页数量")


class ResumeEvaluationStatusUpdate(BaseModel):
    """更新简历复核状态。"""

    status: ResumeStatus = Field(description="pending / interview / rejected")
