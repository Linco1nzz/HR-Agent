import { ApiError, http, notifyUnauthorized } from '@/api/http'
import type {
  ApiErrorBody,
  GenerateScoringCriteriaPayload,
  GenerateScoringCriteriaResponse,
  ScoringCriteria,
  ScoringCriteriaListResponse,
  ScoringCriteriaPayload,
  ScoringCriteriaStatus,
} from '@/api/types'
import { getToken } from '@/utils/storage'
import { consumeSse } from '@/utils/sse'

const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')

export interface ScoringCriteriaListParams {
  page?: number
  page_size?: number
  keyword?: string
  status?: ScoringCriteriaStatus | ''
  job_description_id?: string
}

export async function listScoringCriteria(
  params: ScoringCriteriaListParams = {},
): Promise<ScoringCriteriaListResponse> {
  const { data } = await http.get<ScoringCriteriaListResponse>('/scoring-criteria', {
    params: {
      page: params.page ?? 1,
      page_size: params.page_size ?? 10,
      ...(params.keyword ? { keyword: params.keyword } : {}),
      ...(params.status ? { status: params.status } : {}),
      ...(params.job_description_id ? { job_description_id: params.job_description_id } : {}),
    },
  })
  return data
}

export async function getScoringCriteria(id: string): Promise<ScoringCriteria> {
  const { data } = await http.get<ScoringCriteria>(`/scoring-criteria/${id}`)
  return data
}

export async function createScoringCriteria(
  payload: ScoringCriteriaPayload,
): Promise<ScoringCriteria> {
  const { data } = await http.post<ScoringCriteria>('/scoring-criteria', payload)
  return data
}

export async function updateScoringCriteria(
  id: string,
  payload: Partial<ScoringCriteriaPayload>,
): Promise<ScoringCriteria> {
  const { data } = await http.patch<ScoringCriteria>(`/scoring-criteria/${id}`, payload)
  return data
}

export async function generateScoringCriteria(
  payload: GenerateScoringCriteriaPayload,
): Promise<GenerateScoringCriteriaResponse> {
  // 保留阻塞式接口，供不需要流式的调用方使用；页面使用 streamGenerateScoringCriteria
  const { data } = await http.post<GenerateScoringCriteriaResponse>(
    '/scoring-criteria/generate',
    payload,
    { timeout: 130_000 },
  )
  return data
}

export interface StreamScoringCriteriaOptions {
  signal?: AbortSignal
  onDelta?: (delta: string) => void
}

/**
 * 真实流式生成简历评分标准。
 *
 * 后端返回归一化 SSE：`start` / `delta` / `done` / `error`。收到 `delta` 时回调，
 * 收到 `done` 时 resolve 完整结果；`error` 或非 2xx 会 reject。
 */
export async function streamGenerateScoringCriteria(
  payload: GenerateScoringCriteriaPayload,
  options: StreamScoringCriteriaOptions = {},
): Promise<GenerateScoringCriteriaResponse> {
  const token = getToken()
  const response = await fetch(`${API_BASE}/scoring-criteria/generate/stream`, {
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

  let done: GenerateScoringCriteriaResponse | null = null
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
      done = data as unknown as GenerateScoringCriteriaResponse
    } else if (frame.event === 'error') {
      streamError = new ApiError(
        typeof data.message === 'string' ? data.message : '评分标准生成失败',
        {
          status: typeof data.status === 'number' ? data.status : undefined,
          code: typeof data.code === 'string' ? data.code : undefined,
        },
      )
    }
  })

  if (streamError) throw streamError
  if (!done) throw new ApiError('生成流意外结束，请重试')
  return done
}
