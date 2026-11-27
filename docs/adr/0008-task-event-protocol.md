# 0008. 任务事件协议：计划快照 + 步骤增量

Status: Accepted (2026-11-24)

SSE 事件流 = `task_started`（完整 steps 计划，全部 pending）→ `step`（单步状态变更，含
`result_preview` / `error`）→ `message`（生成类增量文本）→ `confirm_required`（完整
`pending_confirm`，可编辑）→ `task_end`（终态）。SSE 建连时先补发 DB 快照再订阅 Redis，
保证刷新 / 重连不丢已发生的进度；前端由 `AgentChatView` 与 Pinia `agentTask` store 消费这些
事件。理由：计划与增量分离，前端合并简单、单帧体积小，且 DB 快照始终是进度的唯一事实来源。
