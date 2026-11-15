<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'

import { Promotion, VideoPause } from '@element-plus/icons-vue'
import type { InputInstance } from 'element-plus'

const props = defineProps<{
  sending?: boolean
  disabled?: boolean
}>()

const emit = defineEmits<{
  send: [content: string]
  stop: []
}>()

const draft = ref('')
const inputRef = ref<InputInstance>()

function handleSend(): void {
  const content = draft.value.trim()
  if (!content || props.sending || props.disabled) return
  draft.value = ''
  emit('send', content)
  void nextTick(() => inputRef.value?.focus())
}

function handleKeydown(event: Event | KeyboardEvent): void {
  if (!(event instanceof KeyboardEvent)) return
  // Enter 发送、Shift+Enter 换行；中文输入法组词期间不触发发送
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) {
    return
  }
  event.preventDefault()
  handleSend()
}

function focus(): void {
  void nextTick(() => inputRef.value?.focus())
}

watch(
  () => props.sending,
  (sending) => {
    if (!sending) focus()
  },
)

defineExpose({ focus })
</script>

<template>
  <div class="chat-input">
    <el-input
      ref="inputRef"
      v-model="draft"
      type="textarea"
      :autosize="{ minRows: 1, maxRows: 6 }"
      resize="none"
      :disabled="sending || disabled"
      placeholder="输入你的问题，Enter 发送，Shift + Enter 换行"
      @keydown="handleKeydown"
    />
    <div class="chat-input__toolbar">
      <span class="chat-input__hint">
        {{ sending ? 'AI 正在回答，可随时停止生成' : '回答内容由 AI 生成，请注意甄别' }}
      </span>
      <el-button v-if="sending" type="danger" plain :icon="VideoPause" @click="emit('stop')">
        停止生成
      </el-button>
      <el-button
        v-else
        type="primary"
        :icon="Promotion"
        :disabled="!draft.trim() || disabled"
        @click="handleSend"
      >
        发送
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.chat-input {
  display: flex;
  flex: none;
  flex-direction: column;
  gap: 8px;
  padding: 14px 18px 14px;
  background: #ffffff;
  border-top: 1px solid #eef2f7;
}

.chat-input :deep(.el-textarea__inner) {
  padding: 10px 14px;
  font-size: 13.5px;
  line-height: 1.7;
  border-radius: 12px;
  box-shadow: 0 0 0 1px #e2e8f0 inset;
}

.chat-input :deep(.el-textarea__inner:focus) {
  box-shadow: 0 0 0 1px var(--app-primary) inset;
}

.chat-input__toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
}

.chat-input__hint {
  font-size: 11px;
  color: #94a3b8;
}
</style>
