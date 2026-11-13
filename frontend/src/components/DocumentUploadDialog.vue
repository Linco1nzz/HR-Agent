<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { UploadFilled } from '@element-plus/icons-vue'
import { genFileId } from 'element-plus'
import type { UploadFile, UploadRawFile, UploadUserFile } from 'element-plus'

import { uploadKnowledgeBaseDocument } from '@/api/knowledgeBases'
import type { KnowledgeDocument } from '@/api/types'

const MAX_FILE_SIZE_MB = 20
const ACCEPTED_EXTENSIONS = ['.pdf', '.doc', '.docx', '.txt', '.md', '.markdown', '.csv']

const props = defineProps<{
  modelValue: boolean
  knowledgeBaseId: string
  knowledgeBaseName?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  uploaded: [record: KnowledgeDocument]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const fileList = ref<UploadUserFile[]>([])
const uploading = ref(false)

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      reset()
    }
  },
)

function reset(): void {
  fileList.value = []
  uploading.value = false
}

function validateSelectedFile(file: File): boolean {
  const extension = `.${file.name.split('.').pop()?.toLowerCase() ?? ''}`
  if (!ACCEPTED_EXTENSIONS.includes(extension)) {
    ElMessage.warning(`仅支持 ${ACCEPTED_EXTENSIONS.join(' / ')} 格式的文档`)
    fileList.value = []
    return false
  }
  if (file.size === 0) {
    ElMessage.warning('文档内容不能为空')
    fileList.value = []
    return false
  }
  if (file.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
    ElMessage.warning(`文档不能超过 ${MAX_FILE_SIZE_MB}MB`)
    fileList.value = []
    return false
  }
  return true
}

function handleExceed(files: File[]): void {
  const file = files[0] as UploadRawFile | undefined
  if (!file) return
  file.uid = genFileId()
  fileList.value = [file]
  validateSelectedFile(file)
}

function handleFileChange(file: UploadFile): void {
  if (file.raw) {
    validateSelectedFile(file.raw)
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '上传失败，请稍后重试'
}

async function handleSubmit(): Promise<void> {
  if (uploading.value) return

  const file = fileList.value[0]?.raw
  if (!file) {
    ElMessage.warning('请选择要上传的文档')
    return
  }
  if (!validateSelectedFile(file)) return

  uploading.value = true
  try {
    const record = await uploadKnowledgeBaseDocument(props.knowledgeBaseId, file)
    if (record.processing_status === 'failed') {
      ElMessage.warning(
        `文档已上传，但处理失败：${record.processing_error ?? '未知原因'}，可在文档列表中重新处理`,
      )
    } else {
      ElMessage.success(`文档已入库，共 ${record.chunk_count} 个分块`)
    }
    emit('uploaded', record)
    visible.value = false
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="visible"
    title="上传文档"
    width="560px"
    :close-on-click-modal="!uploading"
    :close-on-press-escape="!uploading"
    :show-close="!uploading"
  >
    <el-alert type="info" :closable="false" show-icon class="doc-upload__notice">
      <template #title> 上传到「{{ knowledgeBaseName || '当前知识库' }}」 </template>
      保存后会立即解析正文、按语义切块并向量化入库，耗时取决于文档长度，请耐心等待。
    </el-alert>

    <el-upload
      v-model:file-list="fileList"
      class="doc-upload"
      drag
      :auto-upload="false"
      :limit="1"
      :accept="ACCEPTED_EXTENSIONS.join(',')"
      :on-exceed="handleExceed"
      :on-change="handleFileChange"
    >
      <el-icon class="doc-upload__icon"><UploadFilled /></el-icon>
      <div class="doc-upload__text">拖拽文档到此处，或 <em>点击选择文件</em></div>
      <template #tip>
        <div class="doc-upload__tip">
          支持 PDF / DOC / DOCX / TXT / MD / CSV，单文件不超过 {{ MAX_FILE_SIZE_MB }}MB
        </div>
      </template>
    </el-upload>

    <template #footer>
      <el-button :disabled="uploading" @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="uploading" @click="handleSubmit">
        {{ uploading ? '正在解析并入库…' : '上传并入库' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.doc-upload__notice {
  margin-bottom: 14px;
}

.doc-upload {
  width: 100%;
}

.doc-upload :deep(.el-upload-dragger) {
  padding: 26px 18px;
  background: #f8fbff;
  border-color: #bfdbfe;
  border-radius: 14px;
}

.doc-upload__icon {
  margin-bottom: 8px;
  font-size: 34px;
  color: #2563eb;
}

.doc-upload__text {
  font-size: 13px;
  color: #475569;
}

.doc-upload__text em {
  font-style: normal;
  font-weight: 600;
  color: #2563eb;
}

.doc-upload__tip {
  margin-top: 8px;
  font-size: 11.5px;
  color: #94a3b8;
}
</style>
