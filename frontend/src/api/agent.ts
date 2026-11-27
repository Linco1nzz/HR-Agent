/**
 * HR Agent 接口：发起任务、订阅进度 SSE、确认写操作与确认表单内简历上传。
 *
 * 进度流是「GET + Authorization」的 SSE，原生 EventSource 无法携带请求头，
 * 因此这里统一用 `fetch` 建连、复用 `consumeSse` 逐帧解析。
 */

import { ApiError, http, notifyUnauthorized } from '@/api/http'
import type {
  AgentChatPayload,
  AgentChatResponse,
  AgentConfirm,
  AgentConfirmPayload,
  AgentConfirmResponse,
  AgentConfirmRequiredEvent,
  AgentMessageEvent,
  AgentResumeUploadResponse,
  AgentStep,
  AgentStepEvent,
  AgentTaskEndEvent,
  AgentTaskRead,
  AgentTaskStartedEvent,
  ApiErrorBody,
} from '@/api/types'
import { consumeSse } from '@/utils/sse'
import { getToken } from '@/utils/storage'

const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')

/** 进度流的事件回调。 */
export interface AgentStreamHandlers {
  onTaskStarted?: (task: AgentTaskRead) => void
  onStep?: (step: AgentStep) => void
  /** 生成类步骤的增量文本；`stepIndex` 用于区分文本属于哪个步骤。 */
  onMessage?: (text: string, stepIndex: number) => void
  onConfirmRequired?: (pending: AgentConfirm, taskId: string) => void
  onTaskEnd?: (event: AgentTaskEndEvent) => void
}

export interface AgentStreamOptions extends AgentStreamHandlers {
  signal?: AbortSignal
}

/** 发起一条 Agent 指令；后端立即返回 task_id，进度走 streamTask。 */
export async function chatWithAgent(payload: AgentChatPayload): Promise<AgentChatResponse> {
  const { data } = await http.post<AgentChatResponse>('/agent/chat', payload)
  return data
}

/** 确认 / 取消挂起步骤；Worker 在后台续跑，进度仍走同一条 SSE。 */
export async function confirmAgentTask(
  payload: AgentConfirmPayload,
): Promise<AgentConfirmResponse> {
  const { data } = await http.post<AgentConfirmResponse>('/agent/confirm', payload)
  return data
}

/** 读取任务快照。 */
export async function getTask(taskId: string): Promise<AgentTaskRead> {
  const { data } = await http.get<AgentTaskRead>(`/agent/tasks/${taskId}`)
  return data
}

/** 读取会话中未结束的任务；没有时返回 null（刷新后恢复进度用）。 */
export async function getActiveTask(conversationId: string): Promise<AgentTaskRead | null> {
  const { data } = await http.get<AgentTaskRead | null>(
    `/agent/conversations/${conversationId}/active-task`,
  )
  return data
}

/** 确认表单内上传简历：后端只保存并解析文本，评分在确认后执行。 */
export async function uploadResume(file: File): Promise<AgentResumeUploadResponse> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post<AgentResumeUploadResponse>('/agent/uploads/resume', form, {
    timeout: 120_000,
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

function parsePayload(raw: string): Record<string, unknown> {
  try {
    return JSON.parse(raw) as Record<string, unknown>
  } catch {
    throw new ApiError('进度数据格式异常')
  }
}

/**
 * 订阅任务进度流；`task_end` 后服务端会主动关闭，Promise resolve。
 *
 * 非 2xx 响应抛 `ApiError`（401 同时触发统一登出）；主动 abort 时抛出
 * DOMException（AbortError），调用方按 `signal.aborted` 忽略。
 */
export async function streamTask(taskId: string, handlers: AgentStreamOptions = {}): Promise<void> {
  const token = getToken()
  const response = await fetch(`${API_BASE}/agent/stream/${taskId}`, {
    method: 'GET',
    headers: {
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    signal: handlers.signal,
  })

  if (!response.ok) {
    if (response.status === 401) notifyUnauthorized()
    let body: ApiErrorBody | null = null
    try {
      body = (await response.json()) as ApiErrorBody
    } catch {
      // 非 JSON 错误响应，保留默认提示
    }
    throw new ApiError(body?.message || `请求失败（HTTP ${response.status}）`, {
      status: response.status,
      code: body?.code,
      requestId: body?.request_id ?? undefined,
    })
  }

  if (!response.body) {
    throw new ApiError('响应流不可用，请稍后重试')
  }

  await consumeSse(response.body, (frame) => {
    if (frame.event === 'task_started') {
      const event = parsePayload(frame.data) as unknown as AgentTaskStartedEvent
      handlers.onTaskStarted?.(event.task)
      return
    }
    if (frame.event === 'step') {
      const event = parsePayload(frame.data) as unknown as AgentStepEvent
      handlers.onStep?.(event.step)
      return
    }
    if (frame.event === 'message') {
      const event = parsePayload(frame.data) as unknown as AgentMessageEvent
      if (typeof event.text === 'string') {
        handlers.onMessage?.(
          event.text,
          typeof event.step_index === 'number' ? event.step_index : 0,
        )
      }
      return
    }
    if (frame.event === 'confirm_required') {
      const event = parsePayload(frame.data) as unknown as AgentConfirmRequiredEvent
      handlers.onConfirmRequired?.(event.pending_confirm, event.task_id ?? taskId)
      return
    }
    if (frame.event === 'task_end') {
      const event = parsePayload(frame.data) as unknown as AgentTaskEndEvent
      handlers.onTaskEnd?.({
        task_id: event.task_id ?? taskId,
        status: event.status,
        error: typeof event.error === 'string' ? event.error : null,
      })
      return
    }
    if (frame.event === 'error') {
      const data = parsePayload(frame.data)
      throw new ApiError(
        typeof data.message === 'string' ? data.message : '进度推送暂不可用，请稍后重试',
        {
          status: typeof data.status === 'number' ? data.status : undefined,
          code: typeof data.code === 'string' ? data.code : undefined,
        },
      )
    }
  })
}
