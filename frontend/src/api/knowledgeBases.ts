import { http } from '@/api/http'
import type {
  KnowledgeBase,
  KnowledgeBaseListResponse,
  KnowledgeBasePayload,
  KnowledgeBaseUpdatePayload,
  KnowledgeDocument,
} from '@/api/types'

export interface KnowledgeBaseListParams {
  page?: number
  page_size?: number
  keyword?: string
  category?: string
  is_public?: boolean
}

export async function listKnowledgeBases(
  params: KnowledgeBaseListParams = {},
): Promise<KnowledgeBaseListResponse> {
  const { data } = await http.get<KnowledgeBaseListResponse>('/knowledge-bases', {
    params: {
      page: params.page ?? 1,
      page_size: params.page_size ?? 10,
      ...(params.keyword ? { keyword: params.keyword } : {}),
      ...(params.category ? { category: params.category } : {}),
      ...(params.is_public === undefined ? {} : { is_public: params.is_public }),
    },
  })
  return data
}

export async function getKnowledgeBase(id: string): Promise<KnowledgeBase> {
  const { data } = await http.get<KnowledgeBase>(`/knowledge-bases/${id}`)
  return data
}

export async function createKnowledgeBase(payload: KnowledgeBasePayload): Promise<KnowledgeBase> {
  const { data } = await http.post<KnowledgeBase>('/knowledge-bases', payload)
  return data
}

export async function updateKnowledgeBase(
  id: string,
  payload: KnowledgeBaseUpdatePayload,
): Promise<KnowledgeBase> {
  const { data } = await http.patch<KnowledgeBase>(`/knowledge-bases/${id}`, payload)
  return data
}

export async function deleteKnowledgeBase(id: string): Promise<void> {
  await http.delete(`/knowledge-bases/${id}`)
}

/**
 * 上传文档到知识库。
 *
 * 后端会同步完成解析、切块与向量化，耗时取决于文档长度与 embedding 服务，
 * 单独放宽超时时间。
 */
export async function uploadKnowledgeBaseDocument(
  knowledgeBaseId: string,
  file: File,
): Promise<KnowledgeDocument> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post<KnowledgeDocument>(
    `/knowledge-bases/${knowledgeBaseId}/documents`,
    form,
    {
      timeout: 300_000,
      headers: { 'Content-Type': 'multipart/form-data' },
    },
  )
  return data
}
