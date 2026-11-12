import { http } from '@/api/http'
import { streamGeneration, type StreamOptions } from '@/api/stream'
import type {
  GenerateInterviewPlanPayload,
  GenerateInterviewPlanResponse,
  InterviewPlan,
  InterviewPlanExportFormat,
  InterviewPlanListResponse,
  InterviewPlanPayload,
  InterviewPlanUpdatePayload,
} from '@/api/types'

export interface InterviewPlanListParams {
  page?: number
  page_size?: number
  resume_evaluation_id?: string
  keyword?: string
}

export async function listInterviewPlans(
  params: InterviewPlanListParams = {},
): Promise<InterviewPlanListResponse> {
  const { data } = await http.get<InterviewPlanListResponse>('/interview-plans', {
    params: {
      page: params.page ?? 1,
      page_size: params.page_size ?? 10,
      ...(params.resume_evaluation_id ? { resume_evaluation_id: params.resume_evaluation_id } : {}),
      ...(params.keyword ? { keyword: params.keyword } : {}),
    },
  })
  return data
}

export async function getInterviewPlan(id: string): Promise<InterviewPlan> {
  const { data } = await http.get<InterviewPlan>(`/interview-plans/${id}`)
  return data
}

export async function createInterviewPlan(payload: InterviewPlanPayload): Promise<InterviewPlan> {
  const { data } = await http.post<InterviewPlan>('/interview-plans', payload)
  return data
}

export async function updateInterviewPlan(
  id: string,
  payload: InterviewPlanUpdatePayload,
): Promise<InterviewPlan> {
  const { data } = await http.patch<InterviewPlan>(`/interview-plans/${id}`, payload)
  return data
}

/**
 * 流式生成面试方案。
 *
 * 后端返回归一化 SSE：`start` / `delta` / `done` / `error`；收到 `delta` 时回调，
 * 收到 `done` 时 resolve 完整结果。
 */
export function streamGenerateInterviewPlan(
  payload: GenerateInterviewPlanPayload,
  options: StreamOptions = {},
): Promise<GenerateInterviewPlanResponse> {
  return streamGeneration<GenerateInterviewPlanResponse>(
    '/interview-plans/generate/stream',
    payload,
    {
      ...options,
      fallbackError: '面试方案生成失败',
    },
  )
}

export interface ExportedInterviewPlan {
  blob: Blob
  filename: string
}

function filenameFromDisposition(header: string | undefined): string | null {
  if (!header) return null
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(header)
  if (utf8?.[1]) {
    try {
      return decodeURIComponent(utf8[1])
    } catch {
      return null
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header)
  return plain?.[1] ?? null
}

/** 下载面试方案；默认导出 Word，也可导出 Markdown。 */
export async function exportInterviewPlan(
  id: string,
  format: InterviewPlanExportFormat = 'docx',
): Promise<ExportedInterviewPlan> {
  const response = await http.get<Blob>(`/interview-plans/${id}/export`, {
    params: { format },
    responseType: 'blob',
    timeout: 60_000,
  })
  const extension = format === 'docx' ? 'docx' : 'md'
  return {
    blob: response.data,
    filename:
      filenameFromDisposition(response.headers['content-disposition'] as string | undefined) ??
      `面试方案-${id}.${extension}`,
  }
}
