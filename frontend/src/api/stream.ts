/**
 * 通用流式生成调用。
 *
 * 后端把 Dify 事件归一化为 `start` / `delta` / `done` / `error`，本模块统一处理
 * 鉴权、错误响应与 SSE 帧分发；新增生成功能只需提供接口路径和结果类型。
 */

import { ApiError, notifyUnauthorized } from '@/api/http'
import type { ApiErrorBody } from '@/api/types'
import { consumeSse } from '@/utils/sse'
import { getToken } from '@/utils/storage'

const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')

export interface StreamOptions {
  signal?: AbortSignal
  onDelta?: (delta: string) => void
}

export interface StreamRequestOptions extends StreamOptions {
  /** `error` 事件未携带 message 时的兜底提示。 */
  fallbackError: string
}

/**
 * 以 SSE 调用后端的流式生成接口。
 *
 * 收到 `delta` 时回调，收到 `done` 时 resolve 完整结果；`error` 事件或非 2xx
 * 响应会 reject 为 `ApiError`。
 */
export async function streamGeneration<T>(
  path: string,
  payload: unknown,
  options: StreamRequestOptions,
): Promise<T> {
  const token = getToken()
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
    signal: options.signal,
  })

  if (!response.ok) {
    if (response.status === 401) notifyUnauthorized()
    let body: ApiErrorBody | null = null
    try {
      body = (await response.json()) as ApiErrorBody
    } catch {
      // 非 JSON 错误响应，保留默认提示
    }
    throw new ApiError(body?.message || `生成失败（HTTP ${response.status}）`, {
      status: response.status,
      code: body?.code,
      requestId: body?.request_id ?? undefined,
    })
  }

  if (!response.body) {
    throw new ApiError('生成流不可用，请稍后重试')
  }

  let done: T | null = null
  let streamError: ApiError | null = null

  await consumeSse(response.body, (frame) => {
    let data: Record<string, unknown>
    try {
      data = JSON.parse(frame.data) as Record<string, unknown>
    } catch {
      throw new ApiError('生成流数据格式异常')
    }

    if (frame.event === 'delta') {
      if (typeof data.content === 'string' && options.onDelta) {
        options.onDelta(data.content)
      }
    } else if (frame.event === 'done') {
      done = data as unknown as T
    } else if (frame.event === 'error') {
      streamError = new ApiError(
        typeof data.message === 'string' ? data.message : options.fallbackError,
        {
          status: typeof data.status === 'number' ? data.status : undefined,
          code: typeof data.code === 'string' ? data.code : undefined,
        },
      )
    }
  })

  if (streamError) throw streamError
  if (done === null) throw new ApiError('生成流意外结束，请重试')
  return done
}
