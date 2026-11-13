import { http } from '@/api/http'
import type {
  DocumentChunkListResponse,
  DocumentContentResponse,
  DocumentProcessingStatus,
  KnowledgeDocument,
  KnowledgeDocumentListResponse,
} from '@/api/types'

export interface DocumentListParams {
  page?: number
  page_size?: number
  knowledge_base_id?: string
  unassigned?: boolean
  keyword?: string
  processing_status?: DocumentProcessingStatus | ''
}

export async function listDocuments(
  params: DocumentListParams = {},
): Promise<KnowledgeDocumentListResponse> {
  const { data } = await http.get<KnowledgeDocumentListResponse>('/documents', {
    params: {
      page: params.page ?? 1,
      page_size: params.page_size ?? 10,
      ...(params.knowledge_base_id ? { knowledge_base_id: params.knowledge_base_id } : {}),
      ...(params.unassigned ? { unassigned: true } : {}),
      ...(params.keyword ? { keyword: params.keyword } : {}),
      ...(params.processing_status ? { processing_status: params.processing_status } : {}),
    },
  })
  return data
}

export async function getDocument(id: string): Promise<KnowledgeDocument> {
  const { data } = await http.get<KnowledgeDocument>(`/documents/${id}`)
  return data
}

export async function getDocumentContent(id: string): Promise<DocumentContentResponse> {
  const { data } = await http.get<DocumentContentResponse>(`/documents/${id}/content`)
  return data
}

export async function listDocumentChunks(id: string): Promise<DocumentChunkListResponse> {
  const { data } = await http.get<DocumentChunkListResponse>(`/documents/${id}/chunks`)
  return data
}

export async function reprocessDocument(id: string): Promise<KnowledgeDocument> {
  const { data } = await http.post<KnowledgeDocument>(`/documents/${id}/reprocess`, null, {
    timeout: 300_000,
  })
  return data
}

export async function deleteDocument(id: string): Promise<void> {
  await http.delete(`/documents/${id}`)
}
