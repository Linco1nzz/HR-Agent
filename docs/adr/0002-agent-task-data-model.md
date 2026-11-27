# 0002. Agent 会话复用 conversations/messages，任务用单表

Status: Accepted (2026-11-24)

现有 `conversations` / `messages` 已承载会话列表、消息分页与归属校验，另建一套 agent 会话表会让
列表组件与历史读取复制一份。决定：`conversations` 增加 `kind` 列区分 `knowledge` / `agent`，
消息继续写 `messages`；任务不塞进 `meta_data`，而是新建单表 `agent_tasks`（状态、steps 计划
JSONB、`pending_confirm`、`current_step_index`），不建 step/event 子表。理由：本期不需要事件
游标与跨任务查询，单表足以支撑「挂起—确认—续跑」，并保留后续拆表的空间。
