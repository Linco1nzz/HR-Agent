<script setup lang="ts">
import { computed } from 'vue'

import {
  ChatDotRound,
  Collection,
  Document,
  MagicStick,
  Search,
  UserFilled,
  VideoPause,
} from '@element-plus/icons-vue'

import type { ChatMessage, ChatSource } from '@/api/types'
import JdMarkdown from '@/components/JdMarkdown.vue'

const MAX_VISIBLE_SOURCES = 5

const props = defineProps<{
  message: ChatMessage
  streaming?: boolean
  stopped?: boolean
  error?: string | null
}>()

const emit = defineEmits<{
  'open-source': [source: ChatSource]
  stop: []
}>()

const isAssistant = computed(() => props.message.role === 'assistant')
const context = computed(() => props.message.context)
const isKbRoute = computed(() => context.value?.route === 'kb')

const sources = computed(() => context.value?.sources ?? [])
const visibleSources = computed(() => sources.value.slice(0, MAX_VISIBLE_SOURCES))

const hasRetrieval = computed(() => {
  const ctx = context.value
  if (!ctx) return false
  return Boolean(ctx.rewritten_query || ctx.keywords?.length || ctx.reason)
})

const metaParts = computed(() => {
  const parts: string[] = []
  const {
    response_time: responseTime,
    model_name: modelName,
    tokens_used: tokensUsed,
  } = props.message
  if (responseTime !== null && responseTime !== undefined) {
    parts.push(`耗时 ${formatDuration(responseTime)}`)
  }
  if (modelName) parts.push(`模型 ${modelName}`)
  if (tokensUsed !== null && tokensUsed !== undefined) parts.push(`${tokensUsed} tokens`)
  return parts
})

function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds)) return '—'
  if (seconds < 1) return `${Math.max(1, Math.round(seconds * 1000))} 毫秒`
  return `${seconds.toFixed(1)} 秒`
}

function formatScore(score: number): string {
  return Number.isFinite(score) ? score.toFixed(2) : '—'
}
</script>

<template>
  <div class="chat-msg" :class="isAssistant ? 'chat-msg--assistant' : 'chat-msg--user'">
    <div class="chat-msg__avatar" :class="{ 'chat-msg__avatar--user': !isAssistant }">
      <el-icon :size="17">
        <MagicStick v-if="isAssistant" />
        <UserFilled v-else />
      </el-icon>
    </div>

    <div class="chat-msg__body">
      <div v-if="isAssistant && context" class="chat-msg__route">
        <el-tag size="small" :type="isKbRoute ? 'primary' : 'info'" effect="light" round>
          <el-icon class="chat-msg__route-icon">
            <Collection v-if="isKbRoute" />
            <ChatDotRound v-else />
          </el-icon>
          {{ isKbRoute ? '知识库回答' : '直接回答' }}
        </el-tag>
      </div>

      <div class="chat-msg__bubble">
        <template v-if="!isAssistant">{{ message.content }}</template>

        <template v-else>
          <div v-if="streaming && !message.content" class="chat-msg__thinking">
            <span class="chat-msg__dot" />
            <span class="chat-msg__dot" />
            <span class="chat-msg__dot" />
            <span class="chat-msg__thinking-text">正在思考…</span>
          </div>

          <JdMarkdown v-if="message.content" :content="message.content" />
          <span v-if="streaming && message.content" class="chat-msg__cursor" aria-hidden="true" />

          <el-alert
            v-if="error"
            class="chat-msg__error"
            type="error"
            :title="error"
            show-icon
            :closable="false"
          />
          <p v-if="stopped" class="chat-msg__stopped">已停止生成</p>
        </template>
      </div>

      <el-collapse v-if="isAssistant && hasRetrieval" class="chat-msg__retrieval">
        <el-collapse-item name="retrieval">
          <template #title>
            <span class="chat-msg__retrieval-title">
              <el-icon><Search /></el-icon>
              检索过程
            </span>
          </template>
          <div class="chat-msg__retrieval-body">
            <p v-if="context?.reason">
              <span class="chat-msg__retrieval-label">路由原因</span>
              {{ context.reason }}
            </p>
            <p v-if="context?.rewritten_query">
              <span class="chat-msg__retrieval-label">改写后的问题</span>
              {{ context.rewritten_query }}
            </p>
            <div v-if="context?.keywords?.length" class="chat-msg__keywords">
              <span class="chat-msg__retrieval-label">关键词</span>
              <el-tag
                v-for="keyword in context.keywords"
                :key="keyword"
                size="small"
                type="info"
                effect="plain"
                round
              >
                {{ keyword }}
              </el-tag>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>

      <div v-if="isAssistant && sources.length" class="chat-msg__sources">
        <span class="chat-msg__sources-label">
          <el-icon><Document /></el-icon>
          参考来源
        </span>
        <button
          v-for="source in visibleSources"
          :key="source.chunk_id"
          type="button"
          class="chat-msg__source"
          :title="`查看「${source.document_name}」的分块片段`"
          @click="emit('open-source', source)"
        >
          <span class="chat-msg__source-name">{{ source.document_name }}</span>
          <span class="chat-msg__source-score">{{ formatScore(source.score) }}</span>
        </button>
        <span v-if="sources.length > MAX_VISIBLE_SOURCES" class="chat-msg__sources-more">
          +{{ sources.length - MAX_VISIBLE_SOURCES }}
        </span>
      </div>

      <div v-if="isAssistant && (metaParts.length || streaming)" class="chat-msg__footer">
        <span v-if="metaParts.length">{{ metaParts.join(' · ') }}</span>
        <el-button
          v-if="streaming"
          type="danger"
          text
          size="small"
          :icon="VideoPause"
          @click="emit('stop')"
        >
          停止生成
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-msg {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.chat-msg--user {
  flex-direction: row-reverse;
}

.chat-msg__avatar {
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

.chat-msg__avatar--user {
  color: #475569;
  background: #e2e8f0;
  box-shadow: none;
}

.chat-msg__body {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-width: min(78%, 720px);
  min-width: 0;
}

.chat-msg--user .chat-msg__body {
  align-items: flex-end;
}

.chat-msg__route {
  display: flex;
}

.chat-msg__route-icon {
  margin-right: 3px;
  vertical-align: -2px;
}

.chat-msg__bubble {
  padding: 11px 15px;
  font-size: 13.5px;
  line-height: 1.8;
  background: #ffffff;
  border: 1px solid #e8eef7;
  border-radius: 4px 14px 14px;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
}

.chat-msg--user .chat-msg__bubble {
  color: #ffffff;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  border: none;
  border-radius: 14px 4px 14px 14px;
  box-shadow: 0 6px 16px rgba(37, 99, 235, 0.22);
}

.chat-msg__bubble :deep(.jd-markdown) {
  font-size: 13.5px;
}

.chat-msg__bubble :deep(.jd-markdown > :first-child) {
  margin-top: 0;
}

.chat-msg__bubble :deep(.jd-markdown > :last-child) {
  margin-bottom: 0;
}

.chat-msg__thinking {
  display: flex;
  gap: 4px;
  align-items: center;
  padding: 2px 0;
}

.chat-msg__dot {
  width: 6px;
  height: 6px;
  background: #93b4f5;
  border-radius: 50%;
  animation: chat-dot-bounce 1.2s infinite ease-in-out;
}

.chat-msg__dot:nth-child(2) {
  animation-delay: 0.15s;
}

.chat-msg__dot:nth-child(3) {
  animation-delay: 0.3s;
}

.chat-msg__thinking-text {
  margin-left: 6px;
  font-size: 12px;
  color: #94a3b8;
}

@keyframes chat-dot-bounce {
  0%,
  60%,
  100% {
    transform: translateY(0);
    opacity: 0.5;
  }

  30% {
    transform: translateY(-4px);
    opacity: 1;
  }
}

.chat-msg__cursor {
  display: inline-block;
  width: 7px;
  height: 15px;
  margin-left: 2px;
  vertical-align: -2px;
  background: #2563eb;
  border-radius: 2px;
  animation: chat-cursor-blink 0.9s steps(2, start) infinite;
}

@keyframes chat-cursor-blink {
  to {
    visibility: hidden;
  }
}

.chat-msg__error {
  margin-top: 8px;
}

.chat-msg__stopped {
  margin-top: 6px;
  font-size: 11.5px;
  color: #94a3b8;
}

.chat-msg__retrieval {
  width: 100%;
  background: #f8fafc;
  border: 1px solid #eef2f7;
  border-radius: 10px;
  --el-collapse-header-height: 34px;
  --el-collapse-header-font-size: 12px;
  --el-collapse-content-font-size: 12px;
}

.chat-msg__retrieval :deep(.el-collapse-item__header) {
  padding: 0 12px;
  color: #64748b;
  background: transparent;
  border-bottom: none;
}

.chat-msg__retrieval :deep(.el-collapse-item__wrap) {
  background: transparent;
  border-bottom: none;
}

.chat-msg__retrieval :deep(.el-collapse-item__content) {
  padding: 0 12px 10px;
}

.chat-msg__retrieval-title {
  display: inline-flex;
  gap: 5px;
  align-items: center;
  font-weight: 600;
}

.chat-msg__retrieval-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
  line-height: 1.7;
  color: #475569;
}

.chat-msg__retrieval-label {
  display: inline-block;
  margin-right: 6px;
  font-size: 11px;
  font-weight: 600;
  color: #94a3b8;
}

.chat-msg__keywords {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  align-items: center;
}

.chat-msg__sources {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.chat-msg__sources-label {
  display: inline-flex;
  gap: 4px;
  align-items: center;
  font-size: 11px;
  font-weight: 600;
  color: #94a3b8;
}

.chat-msg__source {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  max-width: 240px;
  padding: 3px 10px;
  cursor: pointer;
  background: #eff6ff;
  border: 1px solid #dbe6fc;
  border-radius: 999px;
  transition:
    background 0.14s ease,
    border-color 0.14s ease;
}

.chat-msg__source:hover {
  background: #dbe6fc;
  border-color: #93b4f5;
}

.chat-msg__source-name {
  overflow: hidden;
  font-size: 11.5px;
  font-weight: 600;
  color: #1d4ed8;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-msg__source-score {
  flex: none;
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 10.5px;
  color: #5b8def;
}

.chat-msg__sources-more {
  font-size: 11px;
  color: #94a3b8;
}

.chat-msg__footer {
  display: flex;
  gap: 10px;
  align-items: center;
  font-size: 11px;
  color: #94a3b8;
}

@media (max-width: 720px) {
  .chat-msg__body {
    max-width: 88%;
  }
}
</style>
