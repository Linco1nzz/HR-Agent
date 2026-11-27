# SPEC_REFACTOR.md：HR Agent 异步任务与 SSE 推送改造指南

## 0. AI 编码助手行为守则（最高优先级）

1. **禁止重造轮子**：你必须在动手写代码前，先全局搜索并理解现有的 Dify Chatflow 调用逻辑、数据库模型和路由结构。
2. **禁止大面积重构**：不要修改现有的 Dify 业务代码。你应该将它们封装或直接作为函数调用，插入到新的 Worker 执行流程中。
3. **增量修改**：优先在已有文件上追加代码，新增文件应控制在最小范围。

------

## 1. 第一步：代码库现状审查（必须首先执行）

在编写任何代码前，请先检索并输出以下信息：

- **现有 API 路由**：定位现有的消息发送接口（可能是 `/chat` 或类似的 WebSocket/HTTP 接口），查看其入参和出参。
- **Dify 调用封装**：查找现有生成 JD、生成评分标准、简历评分、面试方案的函数（如 `call_dify_xxx`）。它们是否接收输入并返回结果？
- **数据库模型**：现有的 User、Session、Message 表结构是什么？是否已有存储聊天历史的结构？
- **前端消息发送**：Vue 3 项目中发送消息的组件位置（如 `ChatInput.vue`）以及接收响应的逻辑（是轮询、WebSocket 还是普通 HTTP 响应？）。

## 2. 第二步：后端改造方案（FastAPI）

### 2.1 复用现有 Dify 调用逻辑

**严禁重写 Dify 请求代码。**
你需要将现有的 4 个业务函数（生成JD、评分标准等）包装成工具列表，供 Worker 循环调用。
*要求：保持原有的异常处理，如果原有代码返回了统一格式，Worker 直接复用。*

### 2.2 路由改造（改造现有接口）

找到现有的发送消息接口（假设为 `POST /api/chat`）：

- **入参**：保留原有的 `session_id` 和 `message`。
- **改造点**：
  1. 生成 `task_id = uuid.uuid4()`。
  2. 将任务持久化（如果在现有表里加字段，请写 Alembic 迁移；如果是新表，请新建 `AgentTask` 表）。
  3. 使用 FastAPI 的 `BackgroundTasks` 触发 Worker：`background_tasks.add_task(worker.run_agent, task_id, session_id, message)`。
  4. **立即返回** `{"task_id": task_id}`，不要等待 Dify 返回。

### 2.3 新增 SSE 流接口

- 新增 `GET /api/stream/{task_id}`。
- 使用 `sse-starlette` 返回 `EventSourceResponse`。
- 逻辑：
  1. 从 DB 查当前 `task_id` 的 `steps` 快照并推送。
  2. 订阅 Redis `task_channel:{task_id}` 持续推送。
- *注意：如果项目原本没有引入 Redis，请使用 Python 的 `asyncio.Queue` 或内存字典作为消息中转（简化版实现）。*

### 2.4 新增确认接口

- 新增 `POST /api/confirm`，接收 `task_id` 和 `action` (confirm/cancel)。
- 逻辑：修改 DB 状态为 `running`，如果有真实删除逻辑则在这里执行；再次触发 Worker 的 `resume` 方法。

### 2.5 定义原子工具注册表

在代码中定义系统支持的所有操作及需要拦截确认的规则：

```python
AVAILABLE_TOOLS = {
    "generate_jd": {"name": "生成JD", "require_confirm": False},
    "generate_criteria": {"name": "生成评分标准", "require_confirm": False},
    "score_resume": {"name": "简历评分", "require_confirm": False},
    "generate_interview": {"name": "生成面试方案", "require_confirm": False},
    "edit_resource": {"name": "编辑资源", "require_confirm": True},   # 拦截
    "delete_resource": {"name": "删除资源", "require_confirm": True}  # 拦截
}
```

### 2.6 LLM 受限规划 (Planner)

接收用户输入后，进行意图识别和任务拆解。

## 3. 第三步：Worker 核心设计（新增代码）

新建 `services/agent_worker.py`。

- **原则**：脱离 HTTP 上下文，所有数据读写必须通过参数或独立创建的 `AsyncSession` 进行。

```python
# 伪代码结构，请根据现有 DB 结构适配
async def run_agent(task_id: str, session_id: str, message: str):
    # 1. 先做意图识别和规划
    # 请复用现有的 LLM 实例或 Dify 工作流规划能力
    steps = await plan_steps(message)
    await update_db_steps(task_id, steps)
    await push_to_redis(task_id, "step", steps)

    for step in plan:
        tool_config = AVAILABLE_TOOLS.get(step["tool"])

        # 1. 拦截确认操作
        if tool_config["require_confirm"]:
            # 构造确认信息
            confirm_data = {"tool": step["tool"], "args": step["args"], "summary": f"即将执行 {tool_config['name']}"}
            # 写入 DB，挂起状态
            await update_task_db(task_id, status="waiting_confirm", pending_confirm=confirm_data)
            # 推送事件
            await push_to_redis(task_id, "confirm_required", confirm_data)
            return # 🔴 关键：Worker 直接退出，释放资源，不阻塞

        # 2. 执行普通步骤
        step["status"] = "running"
        await push_to_redis(task_id, "step", step)

        # 调用现有的业务函数
        result = await execute_tool(step["tool"], step["args"])

        step["status"] = "completed"
        await push_to_redis(task_id, "step", step)

    # 全部完成
    await update_task_db(task_id, status="completed")
    await push_to_redis(task_id, "task_end", {"status": "completed"})


async def resume_agent(task_id: str, action: str):
    task = await get_task_db(task_id)
    pending = task.pending_confirm

    # 将挂起的步骤标记为已处理
    await mark_step_status(task_id, pending["tool"], "completed" if action == "confirm" else "failed")
    await push_to_redis(task_id, "step", {"tool": pending["tool"], "status": "completed"})

    # 继续执行剩余的步骤... (如果 plan 存储在 DB 里，可以循环继续)
    # 简化版：可以再次唤醒 run_agent 处理剩余步骤
```



## 4. 第四步：前端改造（Vue 3）

### 4.1 消息发送逻辑改造

找到现有的发送消息的组件（如 `ChatView.vue`）：

- 将原来的 `await axios.post('/api/chat', ...)`（如果有）改为：

  ```javascript
  const { data } = await axios.post('/api/chat', payload);
  const taskId = data.task_id;
  // 触发 SSE 连接
  connectSSE(taskId);
  ```



### 4.2 新增 SSE Hook (`src/composables/useAgentStream.ts`)

新建（或补充） `useAgentStream`，使用原生 `EventSource`：

```javascript
import { ref } from 'vue';

export function useAgentStream() {
  const steps = ref([]);
  const messageText = ref('');
  const showConfirm = ref(false);
  const confirmData = ref(null);

  const connectSSE = (taskId) => {
    const es = new EventSource(`/api/stream/${taskId}`);

    es.addEventListener('step', (e) => {
      const data = JSON.parse(e.data);
      // 增量合并到 steps 中
      steps.value = mergeSteps(steps.value, data);
    });

    es.addEventListener('message', (e) => {
      messageText.value += JSON.parse(e.data).text;
    });

    es.addEventListener('confirm_required', (e) => {
      confirmData.value = JSON.parse(e.data);
      showConfirm.value = true;
      es.close(); // 挂起时断开，等用户点完再重连
    });

    es.addEventListener('task_end', () => {
      es.close();
    });
  };

  return { steps, messageText, showConfirm, confirmData, connectSSE };
}
```



### 4.3 UI 组件组装

- **进度卡片**：复用 Element Plus 的 `<el-collapse>`。摘要行用 `computed` 取 `steps` 中 `status === 'completed'` 的最后一项。

- **确认弹窗**：使用 `<el-dialog>` 绑定 `showConfirm`，点击确认时：

  ```javascript
  await axios.post('/api/confirm', { task_id, action: 'confirm' });
  showConfirm.value = false;
  connectSSE(task_id); // 确认后必须重连 SSE
  ```



## 5. 数据库及缓存改造注意点

- **Alembic 迁移**：如果需要增加表或字段（如 `task_status`, `pending_confirm` 等），必须编写 Alembic 迁移脚本。
- **Redis 降级方案**：如果项目当前未使用 Redis，请使用 `dict` 在 FastAPI 内存中做简单的 `asyncio.Queue` 消息分发（仅限单实例部署）。
- **session_id 的复用**：确保传给后台 Worker 的 `session_id` 能关联到现有的聊天历史记录表中。
