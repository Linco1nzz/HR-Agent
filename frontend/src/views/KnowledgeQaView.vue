<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'

import { ChatDotRound, Edit, InfoFilled } from '@element-plus/icons-vue'

import {
  createConversation,
  deleteConversation,
  listConversations,
  listMessages,
  updateConversation,
} from '@/api/conversations'
import { listKnowledgeBases } from '@/api/knowledgeBases'
import { streamGeneration } from '@/api/stream'
import type {
  ChatDoneEvent,
  ChatMessage,
  ChatMetaEvent,
  ChatRole,
  ChatSource,
  Conversation,
  KnowledgeBase,
} from '@/api/types'
import ChatInput from '@/components/ChatInput.vue'
import ChatMessageBubble from '@/components/ChatMessage.vue'
import ConversationList from '@/components/ConversationList.vue'
import SourceSnippetDialog from '@/components/SourceSnippetDialog.vue'

/** 在 API 消息之上叠加本地流式状态。 */
interface ChatMessageItem extends ChatMessage {
  streaming: boolean
  stopped: boolean
  error: string | null
}

const CONVERSATION_PAGE_SIZE = 20
const MESSAGE_PAGE_SIZE = 100
const KB_PAGE_SIZE = 100

const suggestions = [
  '公司的年假制度是怎样规定的？',
  '试用期转正的流程和考核要求是什么？',
  '加班调休应该如何申请？',
]

const conversations = ref<Conversation[]>([])
const conversationTotal = ref(0)
const conversationPage = ref(1)
const conversationsLoading = ref(false)
const loadingMore = ref(false)

const activeId = ref<string | null>(null)
const messages = ref<ChatMessageItem[]>([])
const messagesLoading = ref(false)

const kbs = ref<KnowledgeBase[]>([])
const kbsLoading = ref(false)
const kbIds = ref<string[]>([])

const sending = ref(false)
const editingTitle = ref(false)
const titleDraft = ref('')

const snippetVisible = ref(false)
const snippetSource = ref<ChatSource | null>(null)

const messagesRef = ref<HTMLElement | null>(null)
const chatInputRef = ref<InstanceType<typeof ChatInput>>()

let activeController: AbortController | null = null
let messageLoadToken = 0
let localSeq = 0

const activeConversation = computed(
  () => conversations.value.find((item) => item.id === activeId.value) ?? null,
)
const hasMoreConversations = computed(() => conversations.value.length < conversationTotal.value)

const updatedAtFormatter = new Intl.DateTimeFormat('zh-CN', {
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
})

function formatUpdatedAt(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : updatedAtFormatter.format(date)
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '操作失败，请稍后重试'
}

function toItem(message: ChatMessage): ChatMessageItem {
  return { ...message, streaming: false, stopped: false, error: null }
}

function createLocalMessage(
  id: string,
  role: ChatRole,
  content: string,
  conversationId: string,
): ChatMessageItem {
  return {
    id,
    conversation_id: conversationId,
    role,
    content,
    model_name: null,
    tokens_used: null,
    response_time: null,
    context: null,
    meta_data: null,
    rating: null,
    feedback: null,
    parent_message_id: null,
    created_at: new Date().toISOString(),
    streaming: false,
    stopped: false,
    error: null,
  }
}

function isNearBottom(): boolean {
  const el = messagesRef.value
  if (!el) return true
  return el.scrollHeight - el.scrollTop - el.clientHeight < 90
}

async function scrollToBottom(force = false): Promise<void> {
  if (!force && !isNearBottom()) return
  await nextTick()
  const el = messagesRef.value
  if (el) el.scrollTop = el.scrollHeight
}

async function fetchConversations(): Promise<void> {
  conversationsLoading.value = true
  try {
    const result = await listConversations({
      page: 1,
      page_size: CONVERSATION_PAGE_SIZE,
      // 只显示知识问议会话，避免混入 HR Agent 会话
      kind: 'knowledge',
    })
    conversations.value = result.items
    conversationTotal.value = result.total
    conversationPage.value = 1
  } catch (error) {
    conversations.value = []
    conversationTotal.value = 0
    ElMessage.error(errorMessage(error))
  } finally {
    conversationsLoading.value = false
  }
}

async function loadMoreConversations(): Promise<void> {
  if (loadingMore.value || !hasMoreConversations.value) return
  loadingMore.value = true
  try {
    const nextPage = conversationPage.value + 1
    const result = await listConversations({
      page: nextPage,
      page_size: CONVERSATION_PAGE_SIZE,
      kind: 'knowledge',
    })
    const existing = new Set(conversations.value.map((item) => item.id))
    conversations.value.push(...result.items.filter((item) => !existing.has(item.id)))
    conversationTotal.value = result.total
    conversationPage.value = nextPage
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    loadingMore.value = false
  }
}

async function fetchKnowledgeBases(): Promise<void> {
  kbsLoading.value = true
  try {
    const first = await listKnowledgeBases({ page: 1, page_size: KB_PAGE_SIZE })
    const items = [...first.items]
    const pages = Math.ceil(first.total / KB_PAGE_SIZE)
    for (let page = 2; page <= pages; page += 1) {
      const result = await listKnowledgeBases({ page, page_size: KB_PAGE_SIZE })
      items.push(...result.items)
    }
    kbs.value = items
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    kbsLoading.value = false
  }
}

async function loadMessages(conversationId: string): Promise<void> {
  const token = ++messageLoadToken
  messagesLoading.value = true
  messages.value = []
  try {
    const first = await listMessages(conversationId, { page: 1, page_size: MESSAGE_PAGE_SIZE })
    const items = [...first.items]
    const pages = Math.ceil(first.total / MESSAGE_PAGE_SIZE)
    for (let page = 2; page <= pages; page += 1) {
      const result = await listMessages(conversationId, { page, page_size: MESSAGE_PAGE_SIZE })
      items.push(...result.items)
    }
    if (token !== messageLoadToken) return
    messages.value = items.map(toItem)
    void scrollToBottom(true)
  } catch (error) {
    if (token !== messageLoadToken) return
    ElMessage.error(errorMessage(error))
  } finally {
    if (token === messageLoadToken) messagesLoading.value = false
  }
}

/** 中断进行中的流并把流式气泡标记为已停止。 */
function stopStream(): void {
  sending.value = false
  if (!activeController) return

  const controller = activeController
  activeController = null
  controller.abort()

  const last = messages.value[messages.value.length - 1]
  if (last && last.role === 'assistant' && last.streaming) {
    last.streaming = false
    last.stopped = true
  }
}

function resetToDraft(): void {
  stopStream()
  messageLoadToken += 1
  activeId.value = null
  messages.value = []
  messagesLoading.value = false
  editingTitle.value = false
}

async function selectConversation(id: string): Promise<void> {
  if (id === activeId.value) return
  stopStream()
  activeId.value = id
  editingTitle.value = false
  const conversation = conversations.value.find((item) => item.id === id)
  kbIds.value = [...(conversation?.knowledge_base_ids ?? [])]
  await loadMessages(id)
}

function handleCreate(): void {
  resetToDraft()
  chatInputRef.value?.focus()
}

function replaceConversation(updated: Conversation): void {
  const index = conversations.value.findIndex((item) => item.id === updated.id)
  if (index >= 0) {
    conversations.value.splice(index, 1, updated)
  }
}

/** 回答完成后把会话置顶并刷新消息数 / 更新时间。 */
function touchConversation(conversationId: string): void {
  const index = conversations.value.findIndex((item) => item.id === conversationId)
  if (index < 0) return
  const conversation = conversations.value[index]
  conversation.total_messages += 2
  conversation.updated_at = new Date().toISOString()
  if (index > 0) {
    conversations.value.splice(index, 1)
    conversations.value.unshift(conversation)
  }
}

async function handleSend(raw: string): Promise<void> {
  const content = raw.trim()
  if (!content || sending.value || messagesLoading.value) return

  let conversationId = activeId.value
  if (!conversationId) {
    try {
      const created = await createConversation({
        title: content.length > 30 ? `${content.slice(0, 30)}…` : content,
        knowledge_base_ids: kbIds.value,
      })
      conversations.value.unshift(created)
      conversationTotal.value += 1
      activeId.value = created.id
      conversationId = created.id
    } catch (error) {
      ElMessage.error(errorMessage(error))
      return
    }
  }

  localSeq += 1
  const userItem = reactive(
    createLocalMessage(`local-user-${localSeq}`, 'user', content, conversationId),
  )
  const assistantItem = reactive(
    createLocalMessage(`pending-assistant-${localSeq}`, 'assistant', '', conversationId),
  )
  assistantItem.streaming = true
  messages.value.push(userItem, assistantItem)
  sending.value = true
  void scrollToBottom(true)

  // 与 JD / 评分标准 / 面试方案同一套流式管线：直接调用 streamGeneration，
  // 问答特有的 meta / sources 事件通过 onEvent 处理。
  const controller = new AbortController()
  activeController = controller
  const isCurrent = (): boolean => activeController === controller

  try {
    const done = await streamGeneration<ChatDoneEvent>(
      `/conversations/${conversationId}/chat`,
      { content },
      {
        signal: controller.signal,
        fallbackError: '回答失败，请稍后重试',
        onDelta: (delta) => {
          if (!isCurrent()) return
          assistantItem.content += delta
          void scrollToBottom()
        },
        onEvent: (event, data) => {
          if (!isCurrent()) return
          if (event === 'meta') {
            const meta = data as unknown as ChatMetaEvent
            userItem.id = meta.user_message_id
            assistantItem.id = meta.assistant_message_id
            assistantItem.context = {
              route: meta.route,
              reason: meta.reason ?? null,
              rewritten_query: meta.rewritten_query ?? null,
              keywords: meta.keywords ?? null,
              sources: null,
            }
          } else if (event === 'sources') {
            assistantItem.context = {
              ...(assistantItem.context ?? { route: 'kb' }),
              sources: (data.sources as ChatSource[] | undefined) ?? [],
            }
          }
        },
      },
    )
    if (!isCurrent()) return
    activeController = null
    assistantItem.streaming = false
    if (done.message_id) assistantItem.id = done.message_id
    assistantItem.model_name = done.model_name ?? null
    assistantItem.tokens_used = done.tokens_used ?? null
    assistantItem.response_time = done.response_time ?? null
    sending.value = false
    touchConversation(conversationId)
    void scrollToBottom()
  } catch (error) {
    // 主动停止 / 切换会话导致的中断不视为错误
    if (!isCurrent() || controller.signal.aborted) return
    activeController = null
    assistantItem.streaming = false
    assistantItem.error = errorMessage(error)
    sending.value = false
    ElMessage.error(errorMessage(error))
    void scrollToBottom()
  }
}

function handleStop(): void {
  if (!activeController) return
  stopStream()
  ElMessage.info('已停止生成')
}

async function handleKbChange(ids: string[]): Promise<void> {
  const conversation = activeConversation.value
  if (!conversation) return
  try {
    const updated = await updateConversation(conversation.id, { knowledge_base_ids: ids })
    replaceConversation(updated)
  } catch (error) {
    kbIds.value = [...conversation.knowledge_base_ids]
    ElMessage.error(errorMessage(error))
  }
}

function startTitleEdit(): void {
  if (!activeConversation.value) return
  titleDraft.value = activeConversation.value.title
  editingTitle.value = true
}

function cancelTitleEdit(): void {
  editingTitle.value = false
}

async function saveTitle(): Promise<void> {
  if (!editingTitle.value) return
  editingTitle.value = false
  const conversation = activeConversation.value
  const title = titleDraft.value.trim()
  if (!conversation || !title || title === conversation.title) return
  try {
    const updated = await updateConversation(conversation.id, { title })
    replaceConversation(updated)
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

async function handleRename(conversation: Conversation): Promise<void> {
  let title: string
  try {
    const result = await ElMessageBox.prompt('请输入新的会话标题', '重命名会话', {
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputValue: conversation.title,
      inputValidator: (value) => (value && value.trim() ? true : '标题不能为空'),
    })
    title = result.value.trim()
  } catch {
    return
  }
  if (!title || title === conversation.title) return

  try {
    const updated = await updateConversation(conversation.id, { title })
    replaceConversation(updated)
    ElMessage.success('会话已重命名')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

async function handleDelete(conversation: Conversation): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `删除「${conversation.title || '新会话'}」后，其聊天记录将无法恢复。`,
      '删除会话？',
      {
        type: 'warning',
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }

  try {
    await deleteConversation(conversation.id)
    conversations.value = conversations.value.filter((item) => item.id !== conversation.id)
    conversationTotal.value = Math.max(0, conversationTotal.value - 1)
    ElMessage.success('会话已删除')

    if (activeId.value === conversation.id) {
      resetToDraft()
      kbIds.value = []
      const next = conversations.value[0]
      if (next) {
        await selectConversation(next.id)
      }
    }
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

function openSource(source: ChatSource): void {
  snippetSource.value = source
  snippetVisible.value = true
}

onMounted(async () => {
  void fetchKnowledgeBases()
  await fetchConversations()
  const first = conversations.value[0]
  if (first) {
    await selectConversation(first.id)
  }
})

onBeforeUnmount(() => {
  activeController?.abort()
  activeController = null
})
</script>

<template>
  <div class="qa-page">
    <section class="qa-header">
      <div>
        <p class="qa-header__eyebrow">知识中心</p>
        <h1>知识问答</h1>
        <p class="qa-header__desc">
          选择知识库后，AI 会优先检索库内文档并标注回答来源；也可以不选知识库，直接由 AI 回答。
        </p>
      </div>
    </section>

    <section class="qa-body">
      <aside class="qa-side" aria-label="会话历史">
        <ConversationList
          :conversations="conversations"
          :active-id="activeId"
          :loading="conversationsLoading"
          :has-more="hasMoreConversations"
          :loading-more="loadingMore"
          @select="selectConversation"
          @create="handleCreate"
          @rename="handleRename"
          @remove="handleDelete"
          @load-more="loadMoreConversations"
        />
      </aside>

      <main class="qa-main">
        <header class="qa-main__header">
          <div class="qa-main__title">
            <div class="qa-main__title-row">
              <el-input
                v-if="editingTitle"
                v-model="titleDraft"
                class="qa-main__title-input"
                size="small"
                maxlength="100"
                @keyup.enter="saveTitle"
                @keyup.esc="cancelTitleEdit"
                @blur="saveTitle"
              />
              <template v-else>
                <h2>{{ activeConversation?.title || '新会话' }}</h2>
                <el-button
                  text
                  size="small"
                  :icon="Edit"
                  :disabled="!activeConversation"
                  aria-label="编辑会话标题"
                  @click="startTitleEdit"
                />
              </template>
            </div>
            <p class="qa-main__subtitle">
              {{
                activeConversation
                  ? `${activeConversation.total_messages} 条消息 · 更新于 ${formatUpdatedAt(activeConversation.updated_at)}`
                  : '发送第一个问题后会自动创建会话'
              }}
            </p>
          </div>

          <el-select
            v-model="kbIds"
            class="qa-main__kb-select"
            multiple
            filterable
            clearable
            collapse-tags
            collapse-tags-tooltip
            :max-collapse-tags="2"
            :loading="kbsLoading"
            placeholder="选择知识库（可多选）"
            @change="handleKbChange"
          >
            <el-option v-for="kb in kbs" :key="kb.id" :label="kb.name" :value="kb.id" />
          </el-select>
        </header>

        <p v-if="!kbIds.length" class="qa-main__hint">
          <el-icon><InfoFilled /></el-icon>
          未选择知识库，将直接由 AI 回答
        </p>

        <div ref="messagesRef" class="qa-messages">
          <el-skeleton v-if="messagesLoading" :rows="6" animated />

          <div v-else-if="!messages.length" class="qa-messages__empty">
            <div class="qa-messages__empty-icon">
              <el-icon :size="30"><ChatDotRound /></el-icon>
            </div>
            <h2>开始一段知识问答</h2>
            <p>
              在上方选择知识库，AI 会检索相关文档片段并给出带来源的回答； 不选知识库时由 AI
              直接回答。
            </p>
            <div class="qa-messages__suggestions">
              <button
                v-for="suggestion in suggestions"
                :key="suggestion"
                type="button"
                class="qa-suggestion"
                @click="handleSend(suggestion)"
              >
                {{ suggestion }}
              </button>
            </div>
          </div>

          <template v-else>
            <ChatMessageBubble
              v-for="item in messages"
              :key="item.id"
              :message="item"
              :streaming="item.streaming"
              :stopped="item.stopped"
              :error="item.error"
              @open-source="openSource"
              @stop="handleStop"
            />
          </template>
        </div>

        <ChatInput
          ref="chatInputRef"
          :sending="sending"
          :disabled="messagesLoading"
          @send="handleSend"
          @stop="handleStop"
        />
      </main>
    </section>

    <SourceSnippetDialog v-model="snippetVisible" :source="snippetSource" />
  </div>
</template>

<style scoped>
.qa-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.qa-header__eyebrow {
  margin-bottom: 6px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1.6px;
  color: #94a3b8;
  text-transform: uppercase;
}

.qa-header h1 {
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.5px;
  color: #0f172a;
}

.qa-header__desc {
  margin-top: 6px;
  font-size: 13px;
  color: #64748b;
}

.qa-body {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 18px;
  height: calc(100vh - 236px);
  min-height: 520px;
}

.qa-side {
  min-height: 0;
  overflow: hidden;
  background: #ffffff;
  border: 1px solid var(--app-border);
  border-radius: 16px;
  box-shadow: var(--app-shadow);
}

.qa-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: #ffffff;
  border: 1px solid var(--app-border);
  border-radius: 16px;
  box-shadow: var(--app-shadow);
}

.qa-main__header {
  display: flex;
  flex: none;
  gap: 16px;
  align-items: flex-start;
  justify-content: space-between;
  padding: 16px 18px 12px;
}

.qa-main__title {
  flex: 1;
  min-width: 0;
}

.qa-main__title-row {
  display: flex;
  gap: 6px;
  align-items: center;
}

.qa-main__title-row h2 {
  overflow: hidden;
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.qa-main__title-input {
  max-width: 360px;
}

.qa-main__subtitle {
  margin-top: 4px;
  font-size: 11.5px;
  color: #94a3b8;
}

.qa-main__kb-select {
  flex: none;
  width: 320px;
}

.qa-main__hint {
  display: flex;
  flex: none;
  gap: 6px;
  align-items: center;
  padding: 0 18px 10px;
  font-size: 11.5px;
  color: #b45309;
}

.qa-messages {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 18px;
  min-height: 0;
  padding: 18px 20px;
  overflow-y: auto;
  background: linear-gradient(180deg, #fbfcfe 0%, #f6f8fc 100%);
  border-top: 1px solid #eef2f7;
}

.qa-messages__empty {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 8px;
  align-items: center;
  justify-content: center;
  padding: 32px 16px;
  text-align: center;
}

.qa-messages__empty-icon {
  display: grid;
  place-items: center;
  width: 60px;
  height: 60px;
  color: #ffffff;
  background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
  border-radius: 18px;
  box-shadow: 0 12px 26px rgba(37, 99, 235, 0.28);
}

.qa-messages__empty h2 {
  margin-top: 8px;
  font-size: 17px;
  font-weight: 700;
  color: #1e293b;
}

.qa-messages__empty p {
  max-width: 440px;
  font-size: 12.5px;
  line-height: 1.8;
  color: #94a3b8;
}

.qa-messages__suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  margin-top: 14px;
}

.qa-suggestion {
  padding: 7px 14px;
  font-size: 12px;
  color: #475569;
  cursor: pointer;
  background: #ffffff;
  border: 1px solid #dbe3ef;
  border-radius: 999px;
  transition:
    color 0.14s ease,
    background 0.14s ease,
    border-color 0.14s ease;
}

.qa-suggestion:hover {
  color: #1d4ed8;
  background: #eff6ff;
  border-color: #93b4f5;
}

@media (max-width: 1100px) {
  .qa-body {
    grid-template-columns: 1fr;
    height: auto;
  }

  .qa-side {
    max-height: 280px;
  }

  .qa-main {
    height: calc(100vh - 420px);
    min-height: 480px;
  }
}

@media (max-width: 720px) {
  .qa-main__header {
    flex-direction: column;
    align-items: stretch;
  }

  .qa-main__kb-select {
    width: 100%;
  }
}
</style>
