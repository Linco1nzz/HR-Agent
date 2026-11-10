import { http } from '@/api/http'
import { streamGeneration, type StreamOptions } from '@/api/stream'
import type {
  GenerateJdPayload,
  GenerateJdResponse,
  JdStatus,
  JobDescription,
  JobDescriptionListResponse,
  JobDescriptionPayload,
} from '@/api/types'

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

/**
 * 真实流式生成 JD。
 *
 * 后端返回归一化 SSE：`start` / `delta` / `done` / `error`。收到 `delta` 时回调，
 * 收到 `done` 时 resolve 完整结果；`error` 或非 2xx 会 reject。
 */
export function streamGenerateJd(
  payload: GenerateJdPayload,
  options: StreamOptions = {},
): Promise<GenerateJdResponse> {
  return streamGeneration<GenerateJdResponse>('/jds/generate/stream', payload, {
    ...options,
    fallbackError: 'JD 生成失败',
  })
}
