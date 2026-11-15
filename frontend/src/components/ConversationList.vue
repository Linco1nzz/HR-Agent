<script setup lang="ts">
import { ChatDotRound, Delete, Edit, Plus } from '@element-plus/icons-vue'

import type { Conversation } from '@/api/types'

defineProps<{
  conversations: Conversation[]
  activeId: string | null
  loading?: boolean
  hasMore?: boolean
  loadingMore?: boolean
}>()

const emit = defineEmits<{
  select: [id: string]
  create: []
  rename: [conversation: Conversation]
  remove: [conversation: Conversation]
  'load-more': []
}>()

const dateFormatter = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

function formatRelativeTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'

  const diff = Date.now() - date.getTime()
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  if (diff < 7 * 86_400_000) return `${Math.floor(diff / 86_400_000)} 天前`
  return dateFormatter.format(date)
}
</script>

<template>
  <div class="conv-panel">
    <div class="conv-panel__header">
      <div class="conv-panel__title">
        <h2>会话历史</h2>
        <el-tag size="small" type="info" effect="plain" round>{{ conversations.length }}</el-tag>
      </div>
      <el-button type="primary" :icon="Plus" class="conv-panel__create" @click="emit('create')">
        新建会话
      </el-button>
    </div>

    <div class="conv-panel__list">
      <el-skeleton v-if="loading && !conversations.length" :rows="5" animated />

      <div v-else-if="!conversations.length" class="conv-panel__empty">
        <el-icon :size="28"><ChatDotRound /></el-icon>
        <p>暂无会话</p>
        <span>点击「新建会话」开始提问</span>
      </div>

      <template v-else>
        <div
          v-for="conversation in conversations"
          :key="conversation.id"
          class="conv-item"
          :class="{ 'is-active': conversation.id === activeId }"
          role="button"
          tabindex="0"
          @click="emit('select', conversation.id)"
          @keydown.enter="emit('select', conversation.id)"
        >
          <div class="conv-item__head">
            <h3>{{ conversation.title || '新会话' }}</h3>
            <div class="conv-item__actions">
              <el-button
                text
                size="small"
                :icon="Edit"
                aria-label="重命名会话"
                @click.stop="emit('rename', conversation)"
              />
              <el-button
                text
                size="small"
                type="danger"
                :icon="Delete"
                aria-label="删除会话"
                @click.stop="emit('remove', conversation)"
              />
            </div>
          </div>
          <div class="conv-item__meta">
            <span>{{ formatRelativeTime(conversation.updated_at) }}</span>
            <span>{{ conversation.total_messages }} 条消息</span>
            <el-tag
              v-if="conversation.status === 'archived'"
              size="small"
              type="info"
              effect="plain"
              round
            >
              已归档
            </el-tag>
          </div>
        </div>

        <el-button
          v-if="hasMore"
          class="conv-panel__more"
          text
          size="small"
          :loading="loadingMore"
          @click="emit('load-more')"
        >
          加载更多
        </el-button>
      </template>
    </div>
  </div>
</template>

<style scoped>
.conv-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.conv-panel__header {
  display: flex;
  flex: none;
  flex-direction: column;
  gap: 10px;
  padding: 16px 14px 12px;
  border-bottom: 1px solid #eef2f7;
}

.conv-panel__title {
  display: flex;
  gap: 8px;
  align-items: center;
}

.conv-panel__title h2 {
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
}

.conv-panel__create {
  width: 100%;
}

.conv-panel__list {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 6px;
  min-height: 0;
  padding: 10px;
  overflow-y: auto;
}

.conv-panel__empty {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: center;
  padding: 40px 12px;
  color: #94a3b8;
}

.conv-panel__empty p {
  font-size: 13px;
  font-weight: 600;
  color: #64748b;
}

.conv-panel__empty span {
  font-size: 11.5px;
}

.conv-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  cursor: pointer;
  background: #ffffff;
  border: 1px solid transparent;
  border-radius: 12px;
  transition:
    background 0.16s ease,
    border-color 0.16s ease;
}

.conv-item:hover {
  background: #f8fafc;
  border-color: #e2e8f0;
}

.conv-item.is-active {
  background: #eff6ff;
  border-color: #bfdbfe;
}

.conv-item__head {
  display: flex;
  gap: 6px;
  align-items: center;
  justify-content: space-between;
}

.conv-item__head h3 {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  font-size: 13px;
  font-weight: 650;
  color: #1e293b;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conv-item.is-active .conv-item__head h3 {
  color: #1d4ed8;
}

.conv-item__actions {
  display: flex;
  flex: none;
  gap: 2px;
  opacity: 0;
  transition: opacity 0.14s ease;
}

.conv-item__actions .el-button + .el-button {
  margin-left: 0;
}

.conv-item:hover .conv-item__actions,
.conv-item:focus-within .conv-item__actions,
.conv-item.is-active .conv-item__actions {
  opacity: 1;
}

.conv-item__meta {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 11px;
  color: #94a3b8;
}

.conv-panel__more {
  flex: none;
  margin-top: 2px;
  color: #64748b;
}
</style>
