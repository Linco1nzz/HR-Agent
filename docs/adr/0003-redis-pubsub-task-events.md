# 0003. 任务事件用 Redis pub/sub 中转

Status: Accepted (2026-11-24)

异步 Worker 与 SSE 连接不在同一调用栈，需要跨请求推送。决定：Worker 把事件 publish 到 Redis
`task_channel:{task_id}`，SSE 接口先查 DB 快照再订阅；不采用进程内 `asyncio.Queue`，也不用
Redis Streams。理由：Redis 已在 docker-compose / `.env` / 健康检查中存在，是 SPEC 的首选方案，
且多 worker 或多副本部署时仍然成立；Streams 的断线补发本期不需要，SSE 重连由 DB 快照兜底。
