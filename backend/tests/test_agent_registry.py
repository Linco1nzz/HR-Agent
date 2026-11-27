"""工具注册表单元测试：白名单、参数强校验与确认规则（不依赖外部服务）。"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from app.core.exceptions import AgentToolValidationError
from app.services.agent import registry

_SPEC_TOOLS = {
    "generate_jd",
    "generate_criteria",
    "score_resume",
    "generate_interview",
    "query_resource",
    "save_resource",
    "edit_resource",
    "delete_resource",
}


def test_available_tools_match_spec() -> None:
    """SPEC 2.5 的可用工具全部注册，且附带中文名与确认规则。"""
    assert set(registry.AVAILABLE_TOOLS) == _SPEC_TOOLS
    for name, config in registry.AVAILABLE_TOOLS.items():
        assert config["name"], name
        assert isinstance(config["require_confirm"], bool)


def test_confirm_rules_follow_adr_0004_0007() -> None:
    """生成前表单（JD / 简历评分）与写操作需要确认，只读查询不需要。"""
    require_confirm = {name: spec.require_confirm for name, spec in registry.TOOL_SPECS.items()}
    assert require_confirm["generate_jd"] is True
    assert require_confirm["score_resume"] is True
    assert require_confirm["generate_criteria"] is False
    assert require_confirm["generate_interview"] is False
    assert require_confirm["query_resource"] is False
    assert require_confirm["save_resource"] is True
    assert require_confirm["edit_resource"] is True
    assert require_confirm["delete_resource"] is True
    # 删除卡片只读，其余写卡片可编辑（ADR 0007）
    assert registry.TOOL_SPECS["delete_resource"].editable is False
    assert registry.TOOL_SPECS["edit_resource"].editable is True
    assert registry.TOOL_SPECS["generate_jd"].editable is True


def test_tool_catalog_is_json_schema() -> None:
    """工具目录能序列化为 JSON Schema，供 Planner 提示词使用。"""
    catalog = registry.tool_catalog()
    assert len(catalog) == len(_SPEC_TOOLS)
    for entry in catalog:
        assert entry["name"] in _SPEC_TOOLS
        assert entry["parameters"]["type"] == "object"
    json.dumps(catalog)


def test_unknown_tool_rejected() -> None:
    """未注册的工具一律拒绝。"""
    with pytest.raises(AgentToolValidationError):
        registry.validate_tool_args("rm_rf", {})


def test_missing_required_param_rejected() -> None:
    """缺必填参数时抛 422 业务异常。"""
    with pytest.raises(AgentToolValidationError) as excinfo:
        registry.validate_tool_args("generate_jd", {})
    assert excinfo.value.code.value == "AGENT_TOOL_INVALID"


def test_extra_param_rejected() -> None:
    """未声明字段被拒绝，避免参数悄悄丢失。"""
    with pytest.raises(AgentToolValidationError):
        registry.validate_tool_args("generate_jd", {"title": "产品经理", "sneaky": 1})


def test_generate_jd_params_normalized() -> None:
    """职位名称去空白后通过校验。"""
    params = registry.validate_tool_args("generate_jd", {"title": " 产品经理 "})
    assert isinstance(params, registry.GenerateJdParams)
    assert params.title == "产品经理"


def test_score_resume_requires_exactly_one_resume_source() -> None:
    """简历评分必须且只能提供一个简历来源。"""
    jd_id = uuid4()
    with pytest.raises(AgentToolValidationError):
        registry.validate_tool_args("score_resume", {"job_description_id": str(jd_id)})
    with pytest.raises(AgentToolValidationError):
        registry.validate_tool_args(
            "score_resume",
            {
                "job_description_id": str(jd_id),
                "resume_evaluation_id": str(uuid4()),
                "upload_id": "abc",
            },
        )
    params = registry.validate_tool_args(
        "score_resume",
        {"job_description_id": str(jd_id), "upload_id": "abc"},
    )
    assert isinstance(params, registry.ScoreResumeParams)
    assert params.upload_id == "abc"


def test_save_and_edit_require_data() -> None:
    """保存 / 编辑必须带字段，空 data 会失败。"""
    with pytest.raises(AgentToolValidationError):
        registry.validate_tool_args("save_resource", {"resource": "jd", "data": {}})
    with pytest.raises(AgentToolValidationError):
        registry.validate_tool_args(
            "edit_resource",
            {"resource": "jd", "resource_id": str(uuid4()), "data": {}},
        )


def test_query_limit_bounds() -> None:
    """查询条数上限受约束。"""
    with pytest.raises(AgentToolValidationError):
        registry.validate_tool_args("query_resource", {"resource": "jd", "limit": 0})
    with pytest.raises(AgentToolValidationError):
        registry.validate_tool_args(
            "query_resource", {"resource": "resume_evaluation", "limit": 99}
        )
