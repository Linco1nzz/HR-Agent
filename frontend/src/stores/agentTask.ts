import { computed, ref } from 'vue'

import { defineStore } from 'pinia'

import { confirmAgentTask, streamTask } from '@/api/agent'
import type {
  AgentConfirm,
  AgentConfirmAction,
  AgentStep,
  AgentTaskRead,
  AgentTaskStatus,
} from '@/api/types'

/** 未结束的任务状态：仍需保持 / 恢复进度流。 */
const ACTIVE_STATUSES: AgentTaskStatus[] = ['created', 'running', 'waiting_confirm']

/** 终态：进度流已结束。 */
const TERMINAL_STATUSES: AgentTaskStatus[] = ['completed', 'failed', 'cancelled']

function isActiveStatus(value: AgentTaskStatus | null): boolean {
  return value !== null && ACTIVE_STATUSES.includes(value)
}

function isTerminalStatus(value: AgentTaskStatus | null): boolean {
  return value !== null && TERMINAL_STATUSES.includes(value)
}

export const useAgentTaskStore = defineStore('agentTask', () => {
  const task = ref<AgentTaskRead | null>(null)
  const status = ref<AgentTaskStatus | null>(null)
  const steps = ref<AgentStep[]>([])
  const pendingConfirm = ref<AgentConfirm | null>(null)
  /** 当前步骤的生成类增量文本。 */
  const streamingText = ref('')
  /** 是否已建立 SSE 连接（等待确认期间连接仍保持）。 */
  const connecting = ref(false)

  // 流式文本所属步骤：切换步骤时重置累加文本
  const streamingStepIndex = ref<number | null>(null)

  // 只保留最近一次连接：token 变化即视为旧流过期，避免竞态写入
  let controller: AbortController | null = null
  let connectionToken = 0

  const isActive = computed(() => isActiveStatus(status.value))
  const isTerminal = computed(() => isTerminalStatus(status.value))

  /** 用任务快照覆盖本地状态（task_started / 刷新恢复共用）。 */
  function applySnapshot(snapshot: AgentTaskRead): void {
    task.value = snapshot
    status.value = snapshot.status
    steps.value = snapshot.steps.map((step) => ({ ...step }))
    pendingConfirm.value = snapshot.pending_confirm
    streamingText.value = ''
    streamingStepIndex.value = null
  }

  /** 刷新恢复：把 active-task 快照装载进来。 */
  function attachTask(snapshot: AgentTaskRead): void {
    applySnapshot(snapshot)
  }

  /** 按 step_index 合并步骤；确认后 Worker 续跑只靠 step 事件体现状态变化。 */
  function mergeStep(step: AgentStep): void {
    const index = steps.value.findIndex((item) => item.step_index === step.step_index)
    if (index >= 0) {
      steps.value.splice(index, 1, { ...step })
    } else {
      steps.value = [...steps.value, { ...step }].sort((a, b) => a.step_index - b.step_index)
    }

    // 步骤已推进说明该步的确认已处理：清掉可能因重连快照残留的确认卡片
    if (
      pendingConfirm.value &&
      step.step_index >= pendingConfirm.value.step_index &&
      step.status !== 'waiting_confirm'
    ) {
      pendingConfirm.value = null
      if (task.value) task.value.pending_confirm = null
    }

    if (step.status === 'running' && status.value === 'waiting_confirm') status.value = 'running'
    if (step.status === 'waiting_confirm') status.value = 'waiting_confirm'

    if (task.value) {
      if (step.step_index > task.value.current_step_index) {
        task.value.current_step_index = step.step_index
      }
      if (status.value) task.value.status = status.value
    }
  }

  function closeStream(abort: boolean): void {
    connectionToken += 1
    if (controller) {
      if (abort) controller.abort()
      controller = null
    }
    connecting.value = false
  }

  /** 断开进度推送，任务本身仍在后台执行。 */
  function disconnect(): void {
    closeStream(true)
  }

  /** 清空本地任务状态并中断流；切换会话 / 发起新任务时调用。 */
  function reset(): void {
    closeStream(true)
    task.value = null
    status.value = null
    steps.value = []
    pendingConfirm.value = null
    streamingText.value = ''
    streamingStepIndex.value = null
  }

  /**
   * 订阅任务进度流。
   *
   * 重复连接时先关掉旧流并让旧流回调失效；`task_end` 后服务端关闭连接，
   * 此时 resolve；主动 abort（reset / disconnect / 切换会话）静默结束。
   */
  async function connect(taskId: string): Promise<void> {
    closeStream(true)
    const token = connectionToken
    const ctrl = new AbortController()
    controller = ctrl
    connecting.value = true

    const isCurrent = (): boolean => token === connectionToken

    try {
      await streamTask(taskId, {
        signal: ctrl.signal,
        onTaskStarted: (snapshot) => {
          if (!isCurrent()) return
          applySnapshot(snapshot)
        },
        onStep: (step) => {
          if (!isCurrent()) return
          mergeStep(step)
        },
        onMessage: (text, stepIndex) => {
          if (!isCurrent()) return
          if (streamingStepIndex.value !== stepIndex) {
            streamingStepIndex.value = stepIndex
            streamingText.value = ''
          }
          streamingText.value += text
        },
        onConfirmRequired: (pending) => {
          if (!isCurrent()) return
          pendingConfirm.value = pending
          status.value = 'waiting_confirm'
          if (task.value) {
            task.value.status = 'waiting_confirm'
            task.value.pending_confirm = pending
          }
          streamingStepIndex.value = null
          streamingText.value = ''
        },
        onTaskEnd: (event) => {
          if (!isCurrent()) return
          status.value = event.status
          pendingConfirm.value = null
          if (task.value) {
            task.value.status = event.status
            task.value.pending_confirm = null
            task.value.error_message = event.error
          }
          // 终态助手汇总会落库，视图随后重新拉取消息
          streamingText.value = ''
          streamingStepIndex.value = null
        },
      })
    } catch (error) {
      // reset / 切换会话 / 手动停止导致的中断不算失败
      if (ctrl.signal.aborted) return
      throw error
    } finally {
      if (isCurrent()) {
        connecting.value = false
        if (controller === ctrl) controller = null
      }
    }
  }

  /** 确认 / 取消挂起的写操作；调用方在流已关闭时重新 connect 同一任务。 */
  async function confirm(
    action: AgentConfirmAction,
    params?: Record<string, unknown>,
  ): Promise<void> {
    const current = task.value
    if (!current) throw new Error('当前没有等待确认的任务')

    const response = await confirmAgentTask({
      task_id: current.id,
      action,
      ...(params ? { params } : {}),
    })

    status.value = response.status
    pendingConfirm.value = null
    if (task.value) {
      task.value.status = response.status
      task.value.pending_confirm = null
    }
  }

  return {
    task,
    status,
    steps,
    pendingConfirm,
    streamingText,
    connecting,
    isActive,
    isTerminal,
    attachTask,
    connect,
    confirm,
    disconnect,
    reset,
  }
})
