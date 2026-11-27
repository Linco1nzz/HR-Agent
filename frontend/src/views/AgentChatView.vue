<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { ChatDotRound, MagicStick, Refresh } from '@element-plus/icons-vue'

import { chatWithAgent, getActiveTask } from '@/api/agent'
import {
  createConversation,
  deleteConversation,
  listConversations,
  listMessages,
  updateConversation,
} from '@/api/conversations'
import type { AgentTaskStatus, ChatMessage, Conversation } from '@/api/types'
import AgentConfirmDialog from '@/components/AgentConfirmDialog.vue'
import AgentStepTimeline from '@/components/AgentStepTimeline.vue'
import ChatInput from '@/components/ChatInput.vue'
import ChatMessageBubble from '@/components/ChatMessage.vue'
import ConversationList from '@/components/ConversationList.vue'
import JdMarkdown from '@/components/JdMarkdown.vue'
import { useAgentTaskStore } from '@/stores/agentTask'

const CONVERSATION_PAGE_SIZE = 20
const MESSAGE_PAGE_SIZE = 100

const suggestions = [
  '帮我生成一个资深前端工程师的 JD',
  '给最近上传的简历按 JD 评分',
  '把刚才生成的 JD 保存下来',
  '看看我保存了哪些评分标准',
]

const RUN_STATUS: Record<
  AgentTaskStatus,
  { label: string; tag: 'primary' | 'success' | 'info' | 'warning' | 'danger' }
> = {
  created: { label: '规划中', tag: 'info' },
  running: { label: '执行中', tag: 'primary' },
  waiting_confirm: { label: '等待确认', tag: 'warning' },
  completed: { label: '已完成', tag: 'success' },
  failed: { label: '失败', tag: 'danger' },
  cancelled: { label: '已取消', tag: 'info' },
}

const agentStore = useAgentTaskStore()

const conversations = ref<Conversation[]>([])
const conversationTotal = ref(0)
const conversationPage = ref(1)
const conversationsLoading = ref(false)
const loadingMore = ref(false)

const activeId = ref<string | null>(null)
const messages = ref<ChatMessage[]>([])
const messagesLoading = ref(false)

const sending = ref(false)
const creatingConversation = ref(false)
const awaitingTask = ref(false)

const confirmVisible = ref(false)
const confirmSubmitting = ref(false)

const messagesRef = ref<HTMLElement | null>(null)
const chatInputRef = ref<InstanceType<typeof ChatInput>>()

let messageLoadToken = 0
let localSeq = 0
/** 用户主动「停止跟随」时为 true：不自动重连、不刷新消息。 */
let stopRequested = false
let disposed = false

const activeConversation = computed(
  () => conversations.value.find((item) => item.id === activeId.value) ?? null,
)
const hasMoreConversations = computed(() => conversations.value.length < conversationTotal.value)

const pendingConfirm = computed(() => agentStore.pendingConfirm)
/** 进度流正在接收（等待确认期间连接仍保持）。 */
const streamActive = computed(() => agentStore.isActive && agentStore.connecting)
/** 任务未结束但进度流已断开：可手动重连。 */
const detached = computed(
  () =>
    agentStore.isActive &&
    !agentStore.connecting &&
    agentStore.task?.conversation_id === activeId.value,
)
const inputDisabled = computed(
  () =>
    sending.value ||
    messagesLoading.value ||
    confirmSubmitting.value ||
    agentStore.isActive ||
    awaitingTask.value,
)

const currentTask = computed(() => {
  const task = agentStore.task
  if (!task || task.conversation_id !== activeId.value) return null
  return task
})
const showRunCard = computed(() => Boolean(currentTask.value) || awaitingTask.value)
const runStatus = computed(() => RUN_STATUS[agentStore.status ?? 'created'])
const runStreamingText = computed(() => (showRunCard.value ? agentStore.streamingText : ''))

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

function conversationTitle(content: string): string {
  return content.length > 30 ? `${content.slice(0, 30)}…` : content
}

function createLocalUserMessage(id: string, content: string, conversationId: string): ChatMessage {
  return {
    id,
    conversation_id: conversationId,
    role: 'user',
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
      kind: 'agent',
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
      kind: 'agent',
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

async function loadMessages(conversationId: string): Promise<void> {
  const token = ++messageLoadToken
  messagesLoading.value = true
  try {
    const first = await listMessages(conversationId, { page: 1, page_size: MESSAGE_PAGE_SIZE })
    const items = [...first.items]
    const pages = Math.ceil(first.total / MESSAGE_PAGE_SIZE)
    for (let page = 2; page <= pages; page += 1) {
      const result = await listMessages(conversationId, {
        page,
        page_size: MESSAGE_PAGE_SIZE,
      })
      items.push(...result.items)
    }
    if (token !== messageLoadToken) return
    messages.value = items
    void scrollToBottom(true)
  } catch (error) {
    if (token !== messageLoadToken) return
    ElMessage.error(errorMessage(error))
  } finally {
    if (token === messageLoadToken) messagesLoading.value = false
  }
}

/**
 * 连接任务进度流；结束时按终态同步持久化消息与会话列表。
 *
 * 流异常中断（非主动 abort）时拉一次任务快照，任务仍活跃则重连一次。
 */
async function connectTask(
  taskId: string,
  conversationId: string,
  allowRetry = true,
): Promise<void> {
  let streamError: unknown = null
  try {
    await agentStore.connect(taskId)
  } catch (error) {
    streamError = error
    awaitingTask.value = false
  }

  if (disposed || stopRequested) {
    stopRequested = false
    return
  }
  if (activeId.value !== conversationId) return

  if (streamError) {
    if (allowRetry && (await recoverActiveTask(conversationId))) return
    if (!disposed && activeId.value === conversationId) {
      ElMessage.error(errorMessage(streamError))
    }
    return
  }

  if (agentStore.isTerminal) {
    // 终态助手汇总已落库，重新拉取消息让汇总气泡出现
    await loadMessages(conversationId)
    if (disposed || activeId.value !== conversationId) return
    await fetchConversations()
    return
  }

  // 进度流意外结束但任务未结束：用快照兜底并重连一次
  if (allowRetry) await recoverActiveTask(conversationId)
}

/** 拉取会话中未结束的任务并重新订阅进度；没有可恢复任务时返回 false。 */
async function recoverActiveTask(conversationId: string): Promise<boolean> {
  try {
    const active = await getActiveTask(conversationId)
    if (disposed || activeId.value !== conversationId || !active) return false
    agentStore.attachTask(active)
    await connectTask(active.id, conversationId, false)
    return true
  } catch {
    return false
  }
}

/** 刷新后恢复未结束的任务：装载快照并重新订阅进度。 */
async function restoreActiveTask(conversationId: string): Promise<void> {
  try {
    const active = await getActiveTask(conversationId)
    if (disposed || activeId.value !== conversationId || !active) return
    agentStore.attachTask(active)
    void connectTask(active.id, conversationId)
  } catch (error) {
    if (activeId.value === conversationId) ElMessage.error(errorMessage(error))
  }
}

async function selectConversation(id: string): Promise<void> {
  if (id === activeId.value) return
  agentStore.reset()
  stopRequested = false
  confirmVisible.value = false
  awaitingTask.value = false
  activeId.value = id
  messages.value = []
  await loadMessages(id)
  await restoreActiveTask(id)
}

async function handleCreate(): Promise<void> {
  if (creatingConversation.value) return
  agentStore.reset()
  stopRequested = false
  confirmVisible.value = false
  awaitingTask.value = false
  creatingConversation.value = true
  try {
    // Agent 会话与知识问议会话分开存放，必须显式指定 kind
    const created = await createConversation({ kind: 'agent' })
    conversations.value.unshift(created)
    conversationTotal.value += 1
    activeId.value = created.id
    messageLoadToken += 1
    messagesLoading.value = false
    messages.value = []
    chatInputRef.value?.focus()
    await restoreActiveTask(created.id)
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    creatingConversation.value = false
  }
}

function replaceConversation(updated: Conversation): void {
  const index = conversations.value.findIndex((item) => item.id === updated.id)
  if (index >= 0) conversations.value.splice(index, 1, updated)
}

async function handleSend(raw: string): Promise<void> {
  const content = raw.trim()
  if (!content || sending.value || messagesLoading.value) return
  if (agentStore.isActive) {
    ElMessage.warning('上一条指令还在执行，请等它结束或先取消')
    return
  }

  sending.value = true
  try {
    let conversationId = activeId.value
    if (!conversationId) {
      const created = await createConversation({
        kind: 'agent',
        title: conversationTitle(content),
      })
      conversations.value.unshift(created)
      conversationTotal.value += 1
      activeId.value = created.id
      conversationId = created.id
      messages.value = []
    }

    const result = await chatWithAgent({ conversation_id: conversationId, content })
    // 默认标题会由后端在首条指令后自动生成，这里先本地同步，避免列表/标题滞后
    const conversation = conversations.value.find((item) => item.id === conversationId)
    if (conversation && conversation.title === '新会话') {
      conversation.title = conversationTitle(content)
    }
    localSeq += 1
    messages.value.push(createLocalUserMessage(`local-user-${localSeq}`, content, conversationId))
    void scrollToBottom(true)

    agentStore.reset()
    awaitingTask.value = true
    void connectTask(result.task_id, conversationId)
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    sending.value = false
  }
}

function handleStop(): void {
  if (!agentStore.connecting) return
  stopRequested = true
  agentStore.disconnect()
  ElMessage.info('已断开进度推送，任务仍在后台执行')
}

function handleReconnect(): void {
  const task = agentStore.task
  if (!task) return
  stopRequested = false
  ElMessage.info('正在重新连接进度推送…')
  void connectTask(task.id, task.conversation_id)
}

async function handleConfirmTask(params?: Record<string, unknown>): Promise<void> {
  const task = agentStore.task
  if (!task || confirmSubmitting.value) return

  confirmSubmitting.value = true
  try {
    await agentStore.confirm('confirm', params)
    confirmVisible.value = false
    // 确认后 Worker 在同一任务续跑：流仍开着就继续接收，否则重连
    if (!agentStore.connecting) {
      awaitingTask.value = false
      void connectTask(task.id, task.conversation_id)
    }
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    confirmSubmitting.value = false
  }
}

async function handleCancelTask(): Promise<void> {
  const task = agentStore.task
  if (!task || confirmSubmitting.value) return

  confirmSubmitting.value = true
  try {
    await agentStore.confirm('cancel')
    confirmVisible.value = false
    ElMessage.info('已取消当前任务')
    if (!agentStore.connecting) void connectTask(task.id, task.conversation_id)
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    confirmSubmitting.value = false
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
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
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
      agentStore.reset()
      confirmVisible.value = false
      activeId.value = null
      messages.value = []
      const next = conversations.value[0]
      if (next) await selectConversation(next.id)
    }
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

// 首个 task_started 快照到达后结束「规划中」占位
watch(
  () => agentStore.task?.id,
  (id) => {
    if (id) awaitingTask.value = false
  },
)

watch(pendingConfirm, (pending) => {
  confirmVisible.value = Boolean(pending)
  if (pending) void scrollToBottom(true)
})

watch(
  () => agentStore.streamingText,
  () => {
    void scrollToBottom()
  },
)

watch(
  () => agentStore.steps.length,
  () => {
    void scrollToBottom()
  },
)

onMounted(async () => {
  await fetchConversations()
  const first = conversations.value[0]
  if (first) await selectConversation(first.id)
})

onBeforeUnmount(() => {
  disposed = true
  agentStore.reset()
})
</script>

<template>
  <div class="agent-page">
    <section class="agent-header">
      <div>
        <p class="agent-header__eyebrow">AI 助手</p>
        <h1>HR Agent</h1>
        <p class="agent-header__desc">
          用自然语言下达 HR 任务：生成 JD、评分简历、保存 / 编辑 /
          删除资源。写操作执行前会先请你确认。
        </p>
      </div>
    </section>

    <section class="agent-body">
      <aside class="agent-side" aria-label="会话历史">
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

      <main class="agent-main">
        <header class="agent-main__header">
          <div class="agent-main__title">
            <h2>{{ activeConversation?.title || '新会话' }}</h2>
            <p class="agent-main__subtitle">
              {{
                activeConversation
                  ? `${activeConversation.total_messages} 条消息 · 更新于 ${formatUpdatedAt(activeConversation.updated_at)}`
                  : '发送第一条指令后会自动创建会话'
              }}
            </p>
          </div>

          <el-tag v-if="pendingConfirm" size="small" type="warning" effect="light" round>
            待确认
          </el-tag>
          <el-tag v-else-if="streamActive" size="small" type="primary" effect="light" round>
            执行中
          </el-tag>
        </header>

        <el-alert
          v-if="detached"
          class="agent-main__notice"
          type="warning"
          :closable="false"
          show-icon
        >
          <template #title>进度推送已断开</template>
          <div class="agent-main__notice-body">
            <span>任务仍在后台执行，重新连接后可继续查看进度。</span>
            <el-button size="small" type="primary" plain :icon="Refresh" @click="handleReconnect">
              重新连接
            </el-button>
          </div>
        </el-alert>

        <el-alert
          v-else-if="pendingConfirm && !confirmVisible"
          class="agent-main__notice"
          type="warning"
          :closable="false"
          show-icon
        >
          <template #title>有一步操作等待你确认</template>
          <div class="agent-main__notice-body">
            <span>{{ pendingConfirm?.summary }}</span>
            <el-button size="small" type="primary" plain @click="confirmVisible = true">
              处理确认
            </el-button>
          </div>
        </el-alert>

        <div ref="messagesRef" class="agent-messages">
          <el-skeleton v-if="messagesLoading" :rows="6" animated />

          <div v-else-if="!messages.length && !showRunCard" class="agent-messages__empty">
            <div class="agent-messages__empty-icon">
              <el-icon :size="30"><ChatDotRound /></el-icon>
            </div>
            <h2>开始使用 HR Agent</h2>
            <p>
              直接用一句话描述你的需求，例如生成 JD、按 JD
              给简历评分，或查看、编辑、删除已保存的资源。 涉及写操作时，执行前会弹出确认卡片。
            </p>
            <div class="agent-messages__suggestions">
              <button
                v-for="suggestion in suggestions"
                :key="suggestion"
                type="button"
                class="agent-suggestion"
                @click="handleSend(suggestion)"
              >
                {{ suggestion }}
              </button>
            </div>
          </div>

          <template v-else>
            <ChatMessageBubble v-for="message in messages" :key="message.id" :message="message" />
          </template>

          <!-- 当前任务的步骤时间线与流式文本 -->
          <section v-if="showRunCard" class="agent-run">
            <div class="agent-run__avatar">
              <el-icon :size="17"><MagicStick /></el-icon>
            </div>

            <div class="agent-run__body">
              <div class="agent-run__head">
                <span class="agent-run__title">执行计划</span>
                <el-tag size="small" :type="runStatus.tag" effect="light" round>
                  {{ runStatus.label }}
                </el-tag>
                <span v-if="currentTask && agentStore.steps.length" class="agent-run__progress">
                  {{
                    Math.min(
                      agentStore.steps.length,
                      (agentStore.task?.current_step_index ?? 0) + 1,
                    )
                  }}
                  / {{ agentStore.steps.length }} 步
                </span>
              </div>

              <AgentStepTimeline
                :steps="agentStore.steps"
                :current-step-index="agentStore.task?.current_step_index ?? 0"
                :task-status="agentStore.status"
              />

              <div v-if="runStreamingText" class="agent-run__stream">
                <JdMarkdown :content="runStreamingText" />
                <span class="agent-run__cursor" aria-hidden="true" />
              </div>

              <p v-if="agentStore.status === 'waiting_confirm'" class="agent-run__hint">
                等待你确认后继续执行，请在确认卡片中处理。
              </p>
              <p v-if="awaitingTask" class="agent-run__hint">正在规划任务…</p>

              <el-alert
                v-if="agentStore.status === 'failed' && agentStore.task?.error_message"
                class="agent-run__error"
                type="error"
                :title="agentStore.task.error_message"
                :closable="false"
                show-icon
              />
            </div>
          </section>
        </div>

        <ChatInput
          ref="chatInputRef"
          :sending="streamActive"
          :disabled="inputDisabled"
          @send="handleSend"
          @stop="handleStop"
        />
      </main>
    </section>

    <AgentConfirmDialog
      v-model="confirmVisible"
      :pending="pendingConfirm"
      :confirming="confirmSubmitting"
      @confirm="handleConfirmTask"
      @cancel="handleCancelTask"
    />
  </div>
</template>

<style scoped>
.agent-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.agent-header__eyebrow {
  margin-bottom: 6px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1.6px;
  color: #94a3b8;
  text-transform: uppercase;
}

.agent-header h1 {
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.5px;
  color: #0f172a;
}

.agent-header__desc {
  margin-top: 6px;
  font-size: 13px;
  color: #64748b;
}

.agent-body {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 18px;
  height: calc(100vh - 236px);
  min-height: 520px;
}

.agent-side {
  min-height: 0;
  overflow: hidden;
  background: #ffffff;
  border: 1px solid var(--app-border);
  border-radius: 16px;
  box-shadow: var(--app-shadow);
}

.agent-main {
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

.agent-main__header {
  display: flex;
  flex: none;
  gap: 16px;
  align-items: flex-start;
  justify-content: space-between;
  padding: 16px 18px 12px;
}

.agent-main__title {
  flex: 1;
  min-width: 0;
}

.agent-main__title h2 {
  overflow: hidden;
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-main__subtitle {
  margin-top: 4px;
  font-size: 11.5px;
  color: #94a3b8;
}

.agent-main__notice {
  flex: none;
  margin: 0 18px 10px;
  width: auto;
}

.agent-main__notice-body {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  line-height: 1.7;
}

.agent-messages {
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

.agent-messages__empty {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 8px;
  align-items: center;
  justify-content: center;
  padding: 32px 16px;
  text-align: center;
}

.agent-messages__empty-icon {
  display: grid;
  place-items: center;
  width: 60px;
  height: 60px;
  color: #ffffff;
  background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
  border-radius: 18px;
  box-shadow: 0 12px 26px rgba(37, 99, 235, 0.28);
}

.agent-messages__empty h2 {
  margin-top: 8px;
  font-size: 17px;
  font-weight: 700;
  color: #1e293b;
}

.agent-messages__empty p {
  max-width: 460px;
  font-size: 12.5px;
  line-height: 1.8;
  color: #94a3b8;
}

.agent-messages__suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  margin-top: 14px;
}

.agent-suggestion {
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

.agent-suggestion:hover {
  color: #1d4ed8;
  background: #eff6ff;
  border-color: #93b4f5;
}

.agent-run {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.agent-run__avatar {
  display: grid;
  flex: none;
  place-items: center;
  width: 34px;
  height: 34px;
  color: #ffffff;
  background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
  border-radius: 11px;
  box-shadow: 0 6px 14px rgba(37, 99, 235, 0.24);
}

.agent-run__body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  max-width: min(78%, 720px);
  padding: 12px 16px;
  background: #ffffff;
  border: 1px solid #e8eef7;
  border-radius: 4px 14px 14px;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
}

.agent-run__head {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.agent-run__title {
  font-size: 12.5px;
  font-weight: 700;
  color: #0f172a;
}

.agent-run__progress {
  font-size: 11px;
  color: #94a3b8;
}

.agent-run__stream {
  padding-top: 8px;
  font-size: 13.5px;
  border-top: 1px dashed #e8eef7;
}

.agent-run__stream :deep(.jd-markdown) {
  font-size: 13.5px;
}

.agent-run__stream :deep(.jd-markdown > :first-child) {
  margin-top: 0;
}

.agent-run__stream :deep(.jd-markdown > :last-child) {
  margin-bottom: 0;
}

.agent-run__cursor {
  display: inline-block;
  width: 7px;
  height: 14px;
  margin-left: 2px;
  vertical-align: -2px;
  background: #2563eb;
  border-radius: 2px;
  animation: agent-cursor-blink 0.9s steps(2, start) infinite;
}

@keyframes agent-cursor-blink {
  to {
    visibility: hidden;
  }
}

.agent-run__hint {
  font-size: 11.5px;
  line-height: 1.7;
  color: #94a3b8;
}

.agent-run__error {
  margin-top: 4px;
}

@media (max-width: 1100px) {
  .agent-body {
    grid-template-columns: 1fr;
    height: auto;
  }

  .agent-side {
    max-height: 280px;
  }

  .agent-main {
    height: calc(100vh - 420px);
    min-height: 480px;
  }
}

@media (max-width: 720px) {
  .agent-run__body {
    max-width: 88%;
  }
}
</style>
