<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'

import { UploadFilled } from '@element-plus/icons-vue'
import { genFileId } from 'element-plus'
import type {
  FormInstance,
  FormRules,
  UploadFile,
  UploadRawFile,
  UploadUserFile,
} from 'element-plus'
import { useRouter } from 'vue-router'

import { uploadResume } from '@/api/resumeEvaluations'
import type { JobDescriptionListItem, ResumeEvaluation } from '@/api/types'

const MAX_FILE_SIZE_MB = 10
const ACCEPTED_EXTENSIONS = ['.pdf', '.doc', '.docx', '.txt']

const props = defineProps<{
  modelValue: boolean
  jds: JobDescriptionListItem[]
  jdsLoading?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  uploaded: [record: ResumeEvaluation]
}>()

const router = useRouter()
const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const formRef = ref<FormInstance>()
const form = reactive({ job_description_id: '' })
const fileList = ref<UploadUserFile[]>([])
const uploading = ref(false)

const rules: FormRules = {
  job_description_id: [{ required: true, message: '请选择用于评分的 JD', trigger: 'change' }],
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      reset()
    }
  },
)

function reset(): void {
  form.job_description_id = ''
  fileList.value = []
  uploading.value = false
  void nextTick(() => formRef.value?.clearValidate())
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

function validateSelectedFile(file: File): boolean {
  const extension = `.${file.name.split('.').pop()?.toLowerCase() ?? ''}`
  if (!ACCEPTED_EXTENSIONS.includes(extension)) {
    ElMessage.warning('仅支持 PDF、DOC、DOCX、TXT 格式的简历')
    fileList.value = []
    return false
  }
  if (file.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
    ElMessage.warning(`简历文件不能超过 ${MAX_FILE_SIZE_MB}MB`)
    fileList.value = []
    return false
  }
  if (file.size === 0) {
    ElMessage.warning('简历文件不能为空')
    fileList.value = []
    return false
  }
  return true
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '上传失败，请稍后重试'
}

async function handleSubmit(): Promise<void> {
  if (uploading.value) return
  try {
    await formRef.value?.validate()
  } catch {
    return
  }

  const file = fileList.value[0]?.raw
  if (!file) {
    ElMessage.warning('请选择简历文件')
    return
  }
  if (!validateSelectedFile(file)) return

  uploading.value = true
  try {
    const record = await uploadResume(file, form.job_description_id)
    ElMessage.success('简历评分完成')
    emit('uploaded', record)
    visible.value = false
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    uploading.value = false
  }
}

function goJd(): void {
  visible.value = false
  void router.push({ name: 'jds' })
}
</script>

<template>
  <el-dialog
    v-model="visible"
    title="上传简历并评分"
    width="560px"
    :close-on-click-modal="!uploading"
    :close-on-press-escape="!uploading"
    :show-close="!uploading"
  >
    <el-alert
      v-if="!jdsLoading && !jds.length"
      type="warning"
      :closable="false"
      show-icon
      class="resume-upload__empty"
    >
      <template #title>暂无可用评分标准</template>
      <p>简历评分必须绑定已存在评分标准的 JD，请先生成评分标准。</p>
      <el-button type="primary" link @click="goJd">去 JD 管理生成</el-button>
    </el-alert>

    <el-form v-else ref="formRef" :model="form" :rules="rules" label-position="top">
      <el-form-item label="选择用于评分的 JD" prop="job_description_id">
        <el-select
          v-model="form.job_description_id"
          class="resume-upload__jd"
          filterable
          placeholder="请选择 JD"
          :loading="jdsLoading"
        >
          <el-option
            v-for="jd in jds"
            :key="jd.id"
            :label="`${jd.title}（${jd.criteria_count} 份评分标准）`"
            :value="jd.id"
          />
        </el-select>
      </el-form-item>

      <el-form-item label="简历文件">
        <el-upload
          v-model:file-list="fileList"
          class="resume-upload"
          drag
          :auto-upload="false"
          :limit="1"
          :accept="ACCEPTED_EXTENSIONS.join(',')"
          :on-exceed="handleExceed"
          :on-change="handleFileChange"
        >
          <el-icon class="resume-upload__icon"><UploadFilled /></el-icon>
          <div class="resume-upload__text">拖拽简历到此处，或 <em>点击选择文件</em></div>
          <template #tip>
            <div class="resume-upload__tip">
              支持 PDF / DOC / DOCX / TXT，单文件不超过 {{ MAX_FILE_SIZE_MB }}MB
            </div>
          </template>
        </el-upload>
      </el-form-item>

      <el-alert type="info" :closable="false" show-icon>
        评分会使用所选 JD 最新的一份评分标准，AI 分析通常需要几十秒，请耐心等待。
      </el-alert>
    </el-form>

    <template #footer>
      <el-button :disabled="uploading" @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="uploading" :disabled="!jds.length" @click="handleSubmit">
        {{ uploading ? '正在评分…' : '上传并评分' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.resume-upload__empty {
  margin-bottom: 12px;
}

.resume-upload__empty p {
  margin: 4px 0;
  font-size: 12px;
  line-height: 1.7;
}

.resume-upload__jd {
  width: 100%;
}

.resume-upload {
  width: 100%;
}

.resume-upload :deep(.el-upload-dragger) {
  padding: 26px 18px;
  background: #f8fbff;
  border-color: #bfdbfe;
  border-radius: 14px;
}

.resume-upload__icon {
  margin-bottom: 8px;
  font-size: 34px;
  color: #2563eb;
}

.resume-upload__text {
  font-size: 13px;
  color: #475569;
}

.resume-upload__text em {
  font-style: normal;
  font-weight: 600;
  color: #2563eb;
}

.resume-upload__tip {
  margin-top: 8px;
  font-size: 11.5px;
  color: #94a3b8;
}
</style>
