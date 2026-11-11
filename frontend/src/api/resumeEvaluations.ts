import { http } from '@/api/http'
import type {
  ResumeEvaluation,
  ResumeEvaluationListResponse,
  ResumeEvaluationStatusPayload,
  ResumeStatus,
} from '@/api/types'

export interface ResumeListParams {
  page?: number
  page_size?: number
  keyword?: string
  status?: ResumeStatus | ''
  job_description_id?: string
}

export async function listResumeEvaluations(
  params: ResumeListParams = {},
): Promise<ResumeEvaluationListResponse> {
  const { data } = await http.get<ResumeEvaluationListResponse>('/resume-evaluations', {
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

export async function getResumeEvaluation(id: string): Promise<ResumeEvaluation> {
  const { data } = await http.get<ResumeEvaluation>(`/resume-evaluations/${id}`)
  return data
}

/**
 * 上传简历并按所选 JD 的最新评分标准评分。
 *
 * AI 评分通常需要几十秒，单独放宽超时时间，避免达到 Axios 全局 15s 限制。
 */
export async function uploadResume(
  file: File,
  jobDescriptionId: string,
): Promise<ResumeEvaluation> {
  const form = new FormData()
  form.append('file', file)
  form.append('job_description_id', jobDescriptionId)
  const { data } = await http.post<ResumeEvaluation>('/resume-evaluations/upload', form, {
    timeout: 180_000,
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function updateResumeStatus(
  id: string,
  status: ResumeStatus,
): Promise<ResumeEvaluation> {
  const payload: ResumeEvaluationStatusPayload = { status }
  const { data } = await http.patch<ResumeEvaluation>(`/resume-evaluations/${id}/status`, payload)
  return data
}
