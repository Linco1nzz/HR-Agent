import { http } from '@/api/http'
import { streamGeneration, type StreamOptions } from '@/api/stream'
import type {
  GenerateScoringCriteriaPayload,
  GenerateScoringCriteriaResponse,
  ScoringCriteria,
  ScoringCriteriaListResponse,
  ScoringCriteriaPayload,
  ScoringCriteriaStatus,
} from '@/api/types'

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

/**
 * 真实流式生成简历评分标准。
 *
 * 后端返回归一化 SSE：`start` / `delta` / `done` / `error`。收到 `delta` 时回调，
 * 收到 `done` 时 resolve 完整结果；`error` 或非 2xx 会 reject。
 */
export function streamGenerateScoringCriteria(
  payload: GenerateScoringCriteriaPayload,
  options: StreamOptions = {},
): Promise<GenerateScoringCriteriaResponse> {
  return streamGeneration<GenerateScoringCriteriaResponse>(
    '/scoring-criteria/generate/stream',
    payload,
    {
      ...options,
      fallbackError: '评分标准生成失败',
    },
  )
}
