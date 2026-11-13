<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { Document, Tickets } from '@element-plus/icons-vue'

import { getDocumentContent, listDocumentChunks } from '@/api/documents'
import type {
  DocumentChunkItem,
  DocumentProcessingStatus,
  KnowledgeDocumentListItem,
} from '@/api/types'

type PreviewTab = 'raw' | 'chunks'
type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'

const statusMeta: Record<DocumentProcessingStatus, { label: string; type: TagType }> = {
  uploaded: { label: '待处理', type: 'info' },
  processing: { label: '处理中', type: 'warning' },
  processed: { label: '已入库', type: 'success' },
  failed: { label: '处理失败', type: 'danger' },
}

const props = defineProps<{
  modelValue: boolean
  document?: KnowledgeDocumentListItem | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const activeTab = ref<PreviewTab>('raw')
const loading = ref(false)
const content = ref('')
const chunks = ref<DocumentChunkItem[]>([])

const currentStatus = computed(() => {
  const status = props.document?.processing_status ?? 'uploaded'
  return statusMeta[status]
})

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      void load()
    }
  },
)

watch(
  () => props.document?.id,
  () => {
    if (props.modelValue) {
      void load()
    }
  },
)

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '加载文档内容失败'
}

async function load(): Promise<void> {
  const target = props.document
  if (!target) return

  activeTab.value = 'raw'
  loading.value = true
  content.value = ''
  chunks.value = []
  try {
    const [raw, chunkResult] = await Promise.all([
      getDocumentContent(target.id),
      listDocumentChunks(target.id),
    ])
    content.value = raw.content
    chunks.value = chunkResult.items
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <el-dialog v-model="visible" title="文档预览" width="880px" top="6vh">
    <template #header>
      <div class="doc-preview__header">
        <div>
          <h3>{{ document?.original_filename || '文档预览' }}</h3>
          <p>
            {{ document?.knowledge_base_name || '未关联知识库' }} ·
            {{ document?.chunk_count ?? 0 }} 个分块
          </p>
        </div>
        <el-tag :type="currentStatus.type" effect="light" round>
          {{ currentStatus.label }}
        </el-tag>
      </div>
    </template>

    <el-alert
      v-if="document?.processing_status === 'failed' && document.processing_error"
      type="error"
      :closable="false"
      show-icon
      class="doc-preview__alert"
      title="该文档处理失败，以下为已解析出的内容"
    >
      {{ document.processing_error }}
    </el-alert>

    <el-skeleton v-if="loading" :rows="10" animated />

    <el-tabs v-else v-model="activeTab" class="doc-preview__tabs">
      <el-tab-pane name="raw">
        <template #label>
          <span class="doc-preview__tab-label">
            <el-icon><Document /></el-icon>
            原始内容
          </span>
        </template>
        <pre v-if="content" class="doc-preview__raw">{{ content }}</pre>
        <el-empty v-else description="暂无解析后的正文" :image-size="80" />
      </el-tab-pane>

      <el-tab-pane name="chunks">
        <template #label>
          <span class="doc-preview__tab-label">
            <el-icon><Tickets /></el-icon>
            分块预览
            <el-tag size="small" type="info" effect="plain">{{ chunks.length }}</el-tag>
          </span>
        </template>

        <div v-if="chunks.length" class="doc-chunks">
          <article v-for="chunk in chunks" :key="chunk.id" class="doc-chunk">
            <header>
              <span class="doc-chunk__index">#{{ chunk.chunk_index + 1 }}</span>
              <span class="doc-chunk__meta">{{ chunk.char_count }} 字符</span>
              <el-tag
                size="small"
                :type="chunk.has_embedding ? 'success' : 'info'"
                effect="plain"
                round
              >
                {{ chunk.has_embedding ? '已向量化' : '未向量化' }}
              </el-tag>
            </header>
            <p class="doc-chunk__content">{{ chunk.content }}</p>
          </article>
        </div>
        <el-empty v-else description="暂无分块，处理完成后可在此查看" :image-size="80" />
      </el-tab-pane>
    </el-tabs>

    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.doc-preview__header {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  justify-content: space-between;
  padding-right: 28px;
}

.doc-preview__header h3 {
  font-size: 16px;
  font-weight: 650;
  color: #0f172a;
}

.doc-preview__header p {
  margin-top: 4px;
  font-size: 12px;
  color: #94a3b8;
}

.doc-preview__alert {
  margin-bottom: 12px;
}

.doc-preview__tabs :deep(.el-tabs__content) {
  max-height: 62vh;
  overflow-y: auto;
}

.doc-preview__tab-label {
  display: inline-flex;
  gap: 6px;
  align-items: center;
}

.doc-preview__raw {
  padding: 16px 18px;
  margin: 0;
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', monospace;
  font-size: 12.5px;
  line-height: 1.8;
  color: #334155;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: #f8fafc;
  border: 1px solid #eef2f7;
  border-radius: 12px;
}

.doc-chunks {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.doc-chunk {
  padding: 14px 16px;
  background: #ffffff;
  border: 1px solid #e8eef7;
  border-radius: 12px;
}

.doc-chunk header {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 8px;
}

.doc-chunk__index {
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 12px;
  font-weight: 700;
  color: #2563eb;
}

.doc-chunk__meta {
  font-size: 11.5px;
  color: #94a3b8;
}

.doc-chunk__content {
  font-size: 12.5px;
  line-height: 1.8;
  color: #475569;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
