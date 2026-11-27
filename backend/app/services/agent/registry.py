"""Agent 原子工具注册表。

所有可被 Planner 选中的操作集中在这里：工具名、中文名、参数 schema、是否需要
人工确认、确认卡片是否可编辑。SPEC 要求的 ``AVAILABLE_TOOLS`` 由本模块导出；
参数模型同一份既作为 LLM function schema，也作为执行前的强校验。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.core.exceptions import AgentToolValidationError

#: 业务资源类型（保存 / 编辑 / 删除 / 查询共用）
ResourceType = Literal["jd", "scoring_criteria", "interview_plan"]

#: 查询资源类型（额外支持简历记录）
QueryResourceType = Literal["jd", "scoring_criteria", "interview_plan", "resume_evaluation"]


class ToolParams(BaseModel):
    """工具参数的公共约束：拒绝未声明的字段，避免参数悄悄丢失。"""

    model_config = ConfigDict(extra="forbid")


class GenerateJdParams(ToolParams):
    """生成 JD 的参数（同时是生成前参数确认表单的字段）。"""

    title: str = Field(min_length=1, max_length=255, description="职位名称")
    department: str | None = Field(default=None, max_length=100, description="所属部门")
    location: str | None = Field(default=None, max_length=100, description="工作地点")
    salary_range: str | None = Field(default=None, max_length=100, description="薪资范围")
    experience_level: str | None = Field(default=None, max_length=100, description="经验等级")
    education: str | None = Field(default=None, max_length=100, description="学历要求")
    job_type: str | None = Field(default=None, max_length=100, description="工作类型")
    skills: list[str] | None = Field(default=None, description="技能要求列表")
    requirements: str | None = Field(default=None, max_length=5_000, description="职位要求")

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("职位名称不能为空")
        return stripped


class GenerateCriteriaParams(ToolParams):
    """根据已保存的 JD 生成评分标准。"""

    job_description_id: UUID = Field(description="已保存的 JD ID")
    title: str | None = Field(default=None, max_length=255, description="标题（可选）")
    total_score: str = Field(default="100", max_length=20, description="总分")
    instructions: str | None = Field(default=None, max_length=2_000, description="额外要求")


class GenerateInterviewParams(ToolParams):
    """根据简历评估记录生成面试方案。"""

    resume_evaluation_id: UUID = Field(description="简历评估记录 ID")
    instructions: str | None = Field(default=None, max_length=2_000, description="额外要求")


class ScoreResumeParams(ToolParams):
    """简历评分：对已有简历重评，或对表单内新上传的简历评分。"""

    job_description_id: UUID = Field(description="目标 JD ID")
    resume_evaluation_id: UUID | None = Field(default=None, description="已有简历记录 ID")
    upload_id: str | None = Field(default=None, max_length=64, description="表单内上传的简历标识")

    @model_validator(mode="after")
    def _exactly_one_resume(self) -> ScoreResumeParams:
        provided = [self.resume_evaluation_id is not None, self.upload_id is not None]
        if sum(provided) != 1:
            raise ValueError("resume_evaluation_id 与 upload_id 必须且只能提供一个")
        return self


class QueryResourceParams(ToolParams):
    """只读查询业务资源，供用户从结果里选择目标。"""

    resource: QueryResourceType = Field(description="资源类型")
    keyword: str | None = Field(default=None, max_length=100, description="关键字")
    limit: int = Field(default=8, ge=1, le=20, description="返回条数上限")


class SaveResourceParams(ToolParams):
    """把生成结果落库（确认卡片的参数即保存字段）。"""

    resource: ResourceType = Field(description="资源类型")
    data: dict[str, Any] = Field(default_factory=dict, description="落库字段")

    @model_validator(mode="after")
    def _require_data(self) -> SaveResourceParams:
        if not self.data:
            raise ValueError("保存内容不能为空")
        return self


class EditResourceParams(ToolParams):
    """编辑已保存资源（确认卡片可修改目标与字段）。"""

    resource: ResourceType = Field(description="资源类型")
    resource_id: UUID = Field(description="资源 ID")
    data: dict[str, Any] = Field(default_factory=dict, description="要修改的字段")

    @model_validator(mode="after")
    def _require_data(self) -> EditResourceParams:
        if not self.data:
            raise ValueError("修改内容不能为空")
        return self


class DeleteResourceParams(ToolParams):
    """删除（软删除）已保存资源；确认卡片只读，防止误改目标。"""

    resource: ResourceType = Field(description="资源类型")
    resource_id: UUID = Field(description="资源 ID")


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """一个工具的执行契约。"""

    name: str
    name_cn: str
    description: str
    params_model: type[BaseModel]
    #: 执行前是否需要人工确认（写操作 / 生成前参数表单）
    require_confirm: bool
    #: 确认卡片是否允许修改参数
    editable: bool


#: 工具注册表：SPEC 的 AVAILABLE_TOOLS 由它派生。
TOOL_SPECS: dict[str, ToolSpec] = {
    "generate_jd": ToolSpec(
        name="generate_jd",
        name_cn="生成 JD",
        description="根据岗位信息生成 JD 正文；执行前以可编辑表单确认参数，生成结果需再确认后才落库。",
        params_model=GenerateJdParams,
        require_confirm=True,
        editable=True,
    ),
    "generate_criteria": ToolSpec(
        name="generate_criteria",
        name_cn="生成评分标准",
        description="根据已保存的 JD 生成简历评分标准；结果不落库，保存需确认。",
        params_model=GenerateCriteriaParams,
        require_confirm=False,
        editable=False,
    ),
    "generate_interview": ToolSpec(
        name="generate_interview",
        name_cn="生成面试方案",
        description="根据简历评估记录生成面试方案；结果不落库，保存需确认。",
        params_model=GenerateInterviewParams,
        require_confirm=False,
        editable=False,
    ),
    "score_resume": ToolSpec(
        name="score_resume",
        name_cn="简历评分",
        description="按 JD 的评分标准对已有简历或表单内上传的简历评分并落库；执行前确认参数。",
        params_model=ScoreResumeParams,
        require_confirm=True,
        editable=True,
    ),
    "query_resource": ToolSpec(
        name="query_resource",
        name_cn="查询资源",
        description="只读查询 JD / 评分标准 / 简历记录 / 面试方案，用于选择目标资源。",
        params_model=QueryResourceParams,
        require_confirm=False,
        editable=False,
    ),
    "save_resource": ToolSpec(
        name="save_resource",
        name_cn="保存资源",
        description="把生成结果落库为 JD / 评分标准 / 面试方案；执行前需确认，可修改落库字段。",
        params_model=SaveResourceParams,
        require_confirm=True,
        editable=True,
    ),
    "edit_resource": ToolSpec(
        name="edit_resource",
        name_cn="编辑资源",
        description="修改已保存的 JD / 评分标准 / 面试方案；执行前需确认。",
        params_model=EditResourceParams,
        require_confirm=True,
        editable=True,
    ),
    "delete_resource": ToolSpec(
        name="delete_resource",
        name_cn="删除资源",
        description="删除（软删除）已保存的 JD / 评分标准 / 面试方案；执行前需确认，确认卡片只读。",
        params_model=DeleteResourceParams,
        require_confirm=True,
        editable=False,
    ),
}

#: SPEC 2.5 要求的原子工具清单：工具名 → 中文名 / 是否需要确认
AVAILABLE_TOOLS: dict[str, dict[str, Any]] = {
    name: {"name": spec.name_cn, "require_confirm": spec.require_confirm}
    for name, spec in TOOL_SPECS.items()
}

#: 单次任务最多允许的步骤数，防止 Planner 拆出不可控的长任务
MAX_PLAN_STEPS = 5


def get_tool(name: str) -> ToolSpec:
    """按工具名取契约；未注册的工具一律拒绝。"""
    spec = TOOL_SPECS.get(name)
    if spec is None:
        raise AgentToolValidationError(
            f"未注册的工具：{name}",
            details={"tool": name, "available": sorted(TOOL_SPECS)},
        )
    return spec


def validate_tool_args(name: str, args: dict[str, Any]) -> BaseModel:
    """按工具的参数 schema 校验参数，失败抛 422 业务异常。"""
    spec = get_tool(name)
    try:
        return spec.params_model.model_validate(args)
    except ValidationError as exc:
        raise AgentToolValidationError(
            f"工具 {spec.name_cn} 的参数不合法",
            details={"tool": name, "errors": _format_errors(exc)},
        ) from exc


def tool_catalog() -> list[dict[str, Any]]:
    """返回供 Planner 提示词使用的工具目录（含 JSON Schema）。"""
    return [
        {
            "name": spec.name,
            "name_cn": spec.name_cn,
            "description": spec.description,
            "require_confirm": spec.require_confirm,
            "parameters": spec.params_model.model_json_schema(),
        }
        for spec in TOOL_SPECS.values()
    ]


def _format_errors(exc: ValidationError) -> list[dict[str, str]]:
    """把 Pydantic 校验错误压成可序列化的简表。"""
    return [
        {"field": ".".join(str(part) for part in error["loc"]), "message": error["msg"]}
        for error in exc.errors()
    ]
