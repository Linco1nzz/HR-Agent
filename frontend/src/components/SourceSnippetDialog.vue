<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { Document, View } from '@element-plus/icons-vue'

import { getDocument } from '@/api/documents'
import type { ChatSource, KnowledgeDocument } from '@/api/types'
import DocumentPreviewDialog from '@/components/DocumentPreviewDialog.vue'

const props = defineProps<{
  modelValue: boolean
  source?: ChatSource | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const previewVisible = ref(false)
const previewDocument = ref<KnowledgeDocument | null>(null)
const documentLoading = ref(false)

watch(
  () => props.modelValue,
  (open) => {
    if (!open) {
      previewVisible.value = false
    }
  },
)

function formatScore(score: number): string {
  return Number.isFinite(score) ? score.toFixed(4) : '—'
}

async function handleViewDocument(): Promise<void> {
  const source = props.source
  if (!source || documentLoading.value) return

  documentLoading.value = true
  try {
    previewDocument.value = await getDocument(source.document_id)
    previewVisible.value = true
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '文档加载失败，可能已被删除')
  } finally {
    documentLoading.value = false
  }
}
</script>

<template>
  <el-dialog v-model="visible" width="720px" top="8vh" append-to-body>
    <template #header>
      <div class="snippet__header">
        <div class="snippet__header-icon">
          <el-icon :size="18"><Document /></el-icon>
        </div>
        <div class="snippet__header-text">
          <h3>{{ source?.document_name || '来源片段' }}</h3>
          <p>知识库检索命中的文档分块，供核对回答依据</p>
        </div>
      </div>
    </template>

    <div v-if="source" class="snippet__meta">
      <el-tag size="small" type="primary" effect="light" round>
        分块 #{{ source.chunk_index + 1 }}
      </el-tag>
      <el-tag size="small" type="success" effect="light" round>
        相关性分数 {{ formatScore(source.score) }}
      </el-tag>
    </div>

    <pre v-if="source" class="snippet__content">{{ source.content }}</pre>
    <el-empty v-else description="暂无片段内容" :image-size="80" />

    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
      <el-button
        type="primary"
        :icon="View"
        :loading="documentLoading"
        :disabled="!source"
        @click="handleViewDocument"
      >
        查看文档
      </el-button>
    </template>
  </el-dialog>

  <!-- append-to-body 透传给内部 el-dialog，避免嵌套对话框的遮罩层级问题 -->
  <DocumentPreviewDialog v-model="previewVisible" :document="previewDocument" append-to-body />
</template>

<style scoped>
.snippet__header {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding-right: 28px;
}

.snippet__header-icon {
  display: grid;
  flex: none;
  place-items: center;
  width: 38px;
  height: 38px;
  color: #2563eb;
  background: #eff6ff;
  border-radius: 11px;
}

.snippet__header-text {
  min-width: 0;
}

.snippet__header-text h3 {
  overflow: hidden;
  font-size: 15px;
  font-weight: 650;
  color: #0f172a;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.snippet__header-text p {
  margin-top: 3px;
  font-size: 11.5px;
  color: #94a3b8;
}

.snippet__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.snippet__content {
  max-height: 52vh;
  padding: 16px 18px;
  margin: 0;
  overflow-y: auto;
  font-family: inherit;
  font-size: 12.5px;
  line-height: 1.9;
  color: #334155;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: #f8fafc;
  border: 1px solid #eef2f7;
  border-radius: 12px;
}
</style>
