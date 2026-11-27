import { http } from '@/api/http'
import type {
  ChatMessage,
  ChatMessageListResponse,
  Conversation,
  ConversationKind,
  ConversationListResponse,
  ConversationPayload,
  ConversationUpdatePayload,
  MessageFeedbackPayload,
} from '@/api/types'

export interface ConversationListParams {
  page?: number
  page_size?: number
  /** 只查某一类会话（知识问答 / HR Agent）；缺省返回全部。 */
  kind?: ConversationKind
}

export interface MessageListParams {
  page?: number
  page_size?: number
}

export async function listConversations(
  params: ConversationListParams = {},
): Promise<ConversationListResponse> {
  const { data } = await http.get<ConversationListResponse>('/conversations', {
    params: {
      page: params.page ?? 1,
      page_size: params.page_size ?? 20,
      ...(params.kind ? { kind: params.kind } : {}),
    },
  })
  return data
}

export async function getConversation(id: string): Promise<Conversation> {
  const { data } = await http.get<Conversation>(`/conversations/${id}`)
  return data
}

export async function createConversation(payload: ConversationPayload): Promise<Conversation> {
  const { data } = await http.post<Conversation>('/conversations', payload)
  return data
}

export async function updateConversation(
  id: string,
  payload: ConversationUpdatePayload,
): Promise<Conversation> {
  const { data } = await http.patch<Conversation>(`/conversations/${id}`, payload)
  return data
}

export async function deleteConversation(id: string): Promise<void> {
  await http.delete(`/conversations/${id}`)
}

/** 消息列表按 created_at 升序返回。 */
export async function listMessages(
  conversationId: string,
  params: MessageListParams = {},
): Promise<ChatMessageListResponse> {
  const { data } = await http.get<ChatMessageListResponse>(
    `/conversations/${conversationId}/messages`,
    {
      params: {
        page: params.page ?? 1,
        page_size: params.page_size ?? 100,
      },
    },
  )
  return data
}

export async function updateMessageFeedback(
  conversationId: string,
  messageId: string,
  payload: MessageFeedbackPayload,
): Promise<ChatMessage> {
  const { data } = await http.patch<ChatMessage>(
    `/conversations/${conversationId}/messages/${messageId}/feedback`,
    payload,
  )
  return data
}

// 流式问答不在此封装：视图直接调用 `streamGeneration`（@/api/stream），
// 通过 onEvent 处理问答特有的 meta / sources 事件，与 JD 等生成接口同一套管线。
