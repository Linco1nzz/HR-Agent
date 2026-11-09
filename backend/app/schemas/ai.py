"""AI / Dify Chatflow 接口的请求与响应模型。

Dify 应用 ``hr_agent`` 的类型是 ``advanced-chat``（Chatflow），因此后端调用的是
``POST /v1/chat-messages``，而不是 Workflow 应用的 ``POST /v1/workflows/run``。
Chatflow 通过开始节点中的数字变量 ``type`` 分支到不同流程，后端在这里把
``type`` 收敛为枚举并合并进 ``inputs``。
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WorkflowType(IntEnum):
    """Dify 开始节点 ``type`` 变量的取值（1–6）。"""

    JD_GENERATION = 1
    RESUME_CRITERIA = 2
    RESUME_EVALUATION = 3
    INTERVIEW_PLAN = 4
    EXAM_GENERATION = 5
    EXAM_GRADING = 6


class WorkflowTypeRead(BaseModel):
    """单个流程类型的说明（供前端渲染类型选择器 / 动态表单）。"""

    type: WorkflowType = Field(description="传给 Dify 的数字类型", examples=[1])
    key: str = Field(description="稳定的英文标识", examples=["jd_generation"])
    name: str = Field(description="中文名称", examples=["JD 生成"])
    description: str = Field(description="流程说明")
    query_required: bool = Field(description="是否必须提供 query")
    query_hint: str = Field(description="query 在当前流程中的含义")
    required_inputs: list[str] = Field(
        default_factory=list,
        description="除 query 外必须提供的 inputs 字段",
        examples=[["jianli"]],
    )


class ChatRequest(BaseModel):
    """调用 Dify Chatflow 的请求。

    ``type`` 是开始节点的分支变量；``inputs`` 中的同名键会被顶层的 ``type``
    覆盖，避免调用方传入不一致的值。
    """

    type: WorkflowType = Field(
        description="流程类型：1 JD 生成、2 简历评价标准、3 简历评价、"
        "4 面试方案、5 试卷生成、6 阅卷评分",
        examples=[1],
    )
    query: str = Field(
        default="",
        max_length=100_000,
        description="用户输入；不同 type 含义不同，见 GET /api/v1/ai/types",
        examples=["请根据以下岗位需求生成一份 JD：..."],
    )
    inputs: dict[str, Any] = Field(
        default_factory=dict,
        description="Dify 开始节点的其他变量，如 jd、jianli、fileContent、evaluationModel",
        examples=[{"jd": "岗位职责：...", "jianli": "候选人简历：..."}],
    )
    conversation_id: str | None = Field(
        default=None,
        max_length=64,
        description="多轮会话 ID；首次调用省略，后续传入上一次响应中的值",
    )
    auto_generate_name: bool = Field(
        default=True,
        description="是否让 Dify 根据首轮对话自动生成会话标题",
    )
    files: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Dify 文件对象列表（可选，需先通过 Dify 文件上传接口取得 upload_file_id）",
    )


class ChatUsage(BaseModel):
    """Dify 返回的 token / 计费信息，字段随模型供应商可能不同。"""

    model_config = ConfigDict(extra="allow")

    prompt_tokens: int | None = Field(default=None, description="提示词 token 数")
    completion_tokens: int | None = Field(default=None, description="生成 token 数")
    total_tokens: int | None = Field(default=None, description="总 token 数")
    total_price: str | None = Field(default=None, description="总费用（字符串避免精度丢失）")
    currency: str | None = Field(default=None, description="币种")
    latency: float | None = Field(default=None, description="总耗时（秒）")
    time_to_first_token: float | None = Field(default=None, description="首 token 耗时（秒）")


class ChatResponse(BaseModel):
    """阻塞模式下 Dify ``/chat-messages`` 的归一化响应。"""

    event: str = Field(default="message", description="Dify 事件名")
    type: WorkflowType = Field(description="本次调用的流程类型")
    task_id: str = Field(default="", description="Dify 任务 ID")
    message_id: str = Field(default="", description="Dify 消息 ID")
    conversation_id: str = Field(default="", description="会话 ID，后续请求回传")
    answer: str = Field(description="模型最终回答")
    mode: str | None = Field(default=None, description="Dify 应用模式，通常为 advanced-chat")
    created_at: int | None = Field(default=None, description="Dify 创建时间（Unix 秒）")
    usage: ChatUsage | None = Field(default=None, description="token / 计费信息")
    retriever_resources: list[dict[str, Any]] = Field(
        default_factory=list,
        description="知识库召回资源",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Dify 原始 metadata（含 usage / retriever_resources 等）",
    )


class DifyParametersResponse(BaseModel):
    """Dify ``GET /parameters`` 的响应（保留未声明字段）。"""

    model_config = ConfigDict(extra="allow")

    opening_statement: str = Field(default="", description="开场白")
    suggested_questions: list[str] = Field(default_factory=list, description="推荐问题")
    user_input_form: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Dify 开始节点变量定义",
    )
    file_upload: dict[str, Any] | None = Field(default=None, description="文件上传配置")
    system_parameters: dict[str, Any] | None = Field(default=None, description="系统限制参数")
