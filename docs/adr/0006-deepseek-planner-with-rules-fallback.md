# 0006. 受限规划用 DeepSeek 直连与规则降级

Status: Accepted (2026-11-24)

SPEC 要求 Planner 做意图识别与任务拆解，并复用现有 LLM 实例或 Dify 规划能力。决定：复用
`qa_service` 同款 `ChatOpenAI`（DeepSeek），要求输出严格 JSON，工具名必须在白名单内、参数经
Pydantic 校验；解析失败或超时降级为关键词规则。理由：Dify Chatflow 以文本为中心、规划分支需在
仓库外配置（版本不可控），直连 LLM 让编排逻辑全部留在仓库内、可单测；规则降级保证外部依赖
故障时核心指令仍可执行。
