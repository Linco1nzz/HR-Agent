import { ApiError, http, notifyUnauthorized } from '@/api/http'
import type {
  ApiErrorBody,
  GenerateJdPayload,
  GenerateJdResponse,
  JdStatus,
  JobDescription,
  JobDescriptionListResponse,
  JobDescriptionPayload,
} from '@/api/types'
import { getToken } from '@/utils/storage'
import { consumeSse } from '@/utils/sse'

const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')

export interface JdListParams {
  page?: number
  page_size?: number
  keyword?: string
  status?: JdStatus | ''
}

export async function listJds(params: JdListParams = {}): Promise<JobDescriptionListResponse> {
  const { data } = await http.get<JobDescriptionListResponse>('/jds', {
    params: {
      page: params.page ?? 1,
      page_size: params.page_size ?? 10,
      ...(params.keyword ? { keyword: params.keyword } : {}),
      ...(params.status ? { status: params.status } : {}),
    },
  })
  return data
}

export async function getJd(id: string): Promise<JobDescription> {
  const { data } = await http.get<JobDescription>(`/jds/${id}`)
  return data
}

export async function createJd(payload: JobDescriptionPayload): Promise<JobDescription> {
  const { data } = await http.post<JobDescription>('/jds', payload)
  return data
}

export async function updateJd(
  id: string,
  payload: Partial<JobDescriptionPayload>,
): Promise<JobDescription> {
  const { data } = await http.patch<JobDescription>(`/jds/${id}`, payload)
  return data
}

export async function generateJd(payload: GenerateJdPayload): Promise<GenerateJdResponse> {
  // 保留阻塞式接口，供不需要流式的调用方使用；页面使用 streamGenerateJd
  const { data } = await http.post<GenerateJdResponse>('/jds/generate', payload, {
    timeout: 130_000,
  })
  return data
}

export interface StreamJdOptions {
  signal?: AbortSignal
  onDelta?: (delta: string) => void
}

/**
 * 真实流式生成 JD。
 *
 * 后端返回归一化 SSE：`start` / `delta` / `done` / `error`。本函数在收到
 * `delta` 时回调，收到 `done` 时 resolve 完整结果；`error` 或非 2xx 会 reject。
 */
export async function streamGenerateJd(
  payload: GenerateJdPayload,
  options: StreamJdOptions = {},
): Promise<GenerateJdResponse> {
  const token = getToken()
  const response = await fetch(`${API_BASE}/jds/generate/stream`, {
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

  let done: GenerateJdResponse | null = null
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
      done = data as unknown as GenerateJdResponse
    } else if (frame.event === 'error') {
      streamError = new ApiError(typeof data.message === 'string' ? data.message : 'JD 生成失败', {
        status: typeof data.status === 'number' ? data.status : undefined,
        code: typeof data.code === 'string' ? data.code : undefined,
      })
    }
  })

  if (streamError) throw streamError
  if (!done) throw new ApiError('生成流意外结束，请重试')
  return done
}
