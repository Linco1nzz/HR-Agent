<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'

import { Edit, MagicStick, Refresh, View } from '@element-plus/icons-vue'
import type { FormInstance, FormRules } from 'element-plus'

import { createJd, streamGenerateJd, updateJd } from '@/api/jds'
import type {
  GenerateJdPayload,
  JdStatus,
  JobDescription,
  JobDescriptionPayload,
} from '@/api/types'
import JdMarkdown from '@/components/JdMarkdown.vue'

type ContentMode = 'empty' | 'streaming' | 'preview' | 'edit'

interface JdFormState {
  title: string
  department: string
  location: string
  salary_range: string
  experience_level: string
  education: string
  job_type: string
  skills: string[]
  content: string
  requirements: string
  status: JdStatus
  conversation_id: string | null
  workflow_type: string
  meta_data: Record<string, unknown> | null
}

const props = defineProps<{
  modelValue: boolean
  mode: 'create' | 'edit'
  jd?: JobDescription | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: [jd: JobDescription]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const isEdit = computed(() => props.mode === 'edit')
const formRef = ref<FormInstance>()
const generating = ref(false)
const saving = ref(false)
const contentMode = ref<ContentMode>('empty')
let streamController: AbortController | null = null

const createEmptyForm = (): JdFormState => ({
  title: '',
  department: '',
  location: '',
  salary_range: '',
  experience_level: '',
  education: '',
  job_type: '',
  skills: [],
  content: '',
  requirements: '',
  status: 'draft',
  conversation_id: null,
  workflow_type: 'jd_generation',
  meta_data: null,
})

const form = reactive<JdFormState>(createEmptyForm())

const rules: FormRules = {
  title: [{ required: true, message: '请输入职位名称', trigger: 'blur' }],
}

const statusOptions: Array<{ value: JdStatus; label: string }> = [
  { value: 'draft', label: '草稿' },
  { value: 'generated', label: 'AI 已生成' },
  { value: 'published', label: '已发布' },
  { value: 'archived', label: '已归档' },
]

function cancelStream(): void {
  if (streamController) {
    streamController.abort()
    streamController = null
  }
}

function isAbortError(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    'name' in error &&
    (error as { name?: unknown }).name === 'AbortError'
  )
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      resetForm()
    } else {
      cancelStream()
    }
  },
)

function resetForm(): void {
  cancelStream()
  if (isEdit.value && props.jd) {
    const jd = props.jd
    Object.assign(form, {
      title: jd.title,
      department: jd.department ?? '',
      location: jd.location ?? '',
      salary_range: jd.salary_range ?? '',
      experience_level: jd.experience_level ?? '',
      education: jd.education ?? '',
      job_type: jd.job_type ?? '',
      skills: [...(jd.skills ?? [])],
      content: jd.content,
      requirements: jd.requirements ?? '',
      status: jd.status,
      conversation_id: jd.conversation_id,
      workflow_type: jd.workflow_type,
      meta_data: jd.meta_data,
    })
    contentMode.value = 'preview'
  } else {
    Object.assign(form, createEmptyForm())
    contentMode.value = 'empty'
  }
  void nextTick(() => formRef.value?.clearValidate())
}

function toGeneratePayload(): GenerateJdPayload {
  return {
    title: form.title.trim(),
    department: form.department || null,
    location: form.location || null,
    salary_range: form.salary_range || null,
    experience_level: form.experience_level || null,
    education: form.education || null,
    job_type: form.job_type || null,
    skills: form.skills.length ? form.skills : null,
    requirements: form.requirements || null,
  }
}

function toSavePayload(): JobDescriptionPayload {
  return {
    ...toGeneratePayload(),
    content: form.content,
    status: form.status,
    conversation_id: form.conversation_id,
    workflow_type: form.workflow_type,
    meta_data: form.meta_data,
  }
}

async function handleGenerate(): Promise<void> {
  if (generating.value) return
  if (!form.title.trim()) {
    ElMessage.warning('请先填写职位名称')
    return
  }

  cancelStream()
  const controller = new AbortController()
  streamController = controller
  generating.value = true
  form.content = ''
  contentMode.value = 'streaming'

  try {
    const result = await streamGenerateJd(toGeneratePayload(), {
      signal: controller.signal,
      onDelta: (delta) => {
        if (!props.modelValue || controller.signal.aborted) return
        form.content += delta
        contentMode.value = 'streaming'
      },
    })
    if (!props.modelValue) return
    form.content = result.content
    form.conversation_id = result.conversation_id || null
    form.workflow_type = result.workflow_type || 'jd_generation'
    form.status = 'generated'
    contentMode.value = 'preview'
    ElMessage.success('JD 已生成，可继续编辑或保存')
  } catch (error) {
    if (isAbortError(error)) return
    ElMessage.error(error instanceof Error ? error.message : 'AI 生成失败，请稍后重试')
    contentMode.value = form.content.trim() ? 'preview' : 'empty'
  } finally {
    if (streamController === controller) {
      streamController = null
    }
    generating.value = false
  }
}

function handleStopGenerating(): void {
  cancelStream()
  generating.value = false
  contentMode.value = form.content.trim() ? 'preview' : 'empty'
}

function handleEditContent(): void {
  contentMode.value = 'edit'
}

function handlePreviewContent(): void {
  contentMode.value = 'preview'
}

async function handleSave(): Promise<void> {
  if (generating.value) return
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  if (!form.content.trim()) {
    contentMode.value = 'edit'
    ElMessage.warning('请先生成或填写 JD 内容')
    return
  }

  saving.value = true
  try {
    const payload = toSavePayload()
    const saved =
      isEdit.value && props.jd ? await updateJd(props.jd.id, payload) : await createJd(payload)
    ElMessage.success(isEdit.value ? 'JD 已更新' : 'JD 已保存')
    emit('saved', saved)
    visible.value = false
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存失败，请稍后重试')
  } finally {
    saving.value = false
  }
}

function handleClose(): void {
  visible.value = false
}

onBeforeUnmount(cancelStream)
</script>

<template>
  <el-drawer
    v-model="visible"
    class="jd-editor-drawer"
    :title="isEdit ? '编辑 JD' : '新建 JD'"
    size="720px"
    destroy-on-close
    @closed="cancelStream"
  >
    <div class="jd-editor">
      <div class="jd-editor__intro">
        <p>
          {{
            isEdit
              ? '修改 JD 的基本信息与正文内容。'
              : '填写岗位信息后，让 AI 生成 JD 草稿，再按需调整。'
          }}
        </p>
      </div>

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <div class="jd-editor__grid">
          <el-form-item label="职位名称" prop="title" class="jd-editor__full">
            <el-input v-model="form.title" maxlength="255" placeholder="例如：高级前端工程师" />
          </el-form-item>

          <el-form-item label="所属部门">
            <el-input v-model="form.department" maxlength="100" placeholder="例如：产品研发" />
          </el-form-item>

          <el-form-item label="工作地点">
            <el-input v-model="form.location" maxlength="100" placeholder="例如：上海 / 远程" />
          </el-form-item>

          <el-form-item label="薪资范围">
            <el-input v-model="form.salary_range" maxlength="100" placeholder="例如：25-40K·14薪" />
          </el-form-item>

          <el-form-item label="经验等级">
            <el-input v-model="form.experience_level" maxlength="100" placeholder="例如：3-5 年" />
          </el-form-item>

          <el-form-item label="学历要求">
            <el-input v-model="form.education" maxlength="100" placeholder="例如：本科及以上" />
          </el-form-item>

          <el-form-item label="工作类型">
            <el-input v-model="form.job_type" maxlength="100" placeholder="例如：全职" />
          </el-form-item>

          <el-form-item label="技能要求" class="jd-editor__full">
            <el-select
              v-model="form.skills"
              class="jd-editor__skills"
              multiple
              filterable
              allow-create
              default-first-option
              :reserve-keyword="false"
              :max-collapse-tags="6"
              placeholder="输入技能后回车，例如：Vue 3、TypeScript"
            />
          </el-form-item>

          <el-form-item label="职位要求 / 补充说明" class="jd-editor__full">
            <el-input
              v-model="form.requirements"
              type="textarea"
              :rows="3"
              maxlength="2000"
              show-word-limit
              placeholder="例如：有大型中后台项目经验、具备良好的沟通能力等"
            />
          </el-form-item>

          <el-form-item v-if="isEdit" label="状态" class="jd-editor__full">
            <el-select v-model="form.status" class="jd-editor__status">
              <el-option
                v-for="option in statusOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
          </el-form-item>
        </div>
      </el-form>

      <section class="jd-content">
        <header class="jd-content__header">
          <div>
            <h3>JD 内容</h3>
            <p>AI 生成时内容会实时出现，也可生成后直接编辑。</p>
          </div>
          <div class="jd-content__actions">
            <template v-if="contentMode === 'empty'">
              <el-button @click="contentMode = 'edit'">直接编辑</el-button>
              <el-button
                type="primary"
                :icon="MagicStick"
                :loading="generating"
                @click="handleGenerate"
              >
                AI 生成 JD
              </el-button>
            </template>
            <template v-else-if="generating">
              <el-button @click="handleStopGenerating">停止生成</el-button>
            </template>
            <template v-else>
              <el-button v-if="contentMode !== 'edit'" :icon="Edit" @click="handleEditContent">
                编辑
              </el-button>
              <el-button v-else :icon="View" @click="handlePreviewContent">预览</el-button>
              <el-button v-if="!isEdit" :icon="Refresh" @click="handleGenerate">
                重新生成
              </el-button>
            </template>
          </div>
        </header>

        <div v-if="contentMode === 'empty'" class="jd-content__empty">
          <div class="jd-content__empty-icon">
            <el-icon :size="24"><MagicStick /></el-icon>
          </div>
          <p>还没有 JD 内容</p>
          <span>填写上方岗位信息后点击“AI 生成 JD”，内容会边生成边显示。</span>
        </div>

        <pre
          v-else-if="contentMode === 'streaming'"
          class="jd-content__typing"
        ><span>{{ form.content }}</span><i class="jd-caret" /></pre>

        <el-input
          v-else-if="contentMode === 'edit'"
          v-model="form.content"
          type="textarea"
          :rows="16"
          resize="vertical"
          placeholder="支持 Markdown，例如：## 岗位职责"
        />

        <div v-else class="jd-content__preview">
          <JdMarkdown :content="form.content" />
        </div>
      </section>
    </div>

    <template #footer>
      <div class="jd-editor__footer">
        <span class="jd-editor__hint">
          {{ form.content ? `${form.content.length} 字符` : '尚未生成内容' }}
        </span>
        <div>
          <el-button @click="handleClose">取消</el-button>
          <el-button type="primary" :loading="saving" :disabled="generating" @click="handleSave">
            保存 JD
          </el-button>
        </div>
      </div>
    </template>
  </el-drawer>
</template>

<style scoped>
.jd-editor {
  display: flex;
  flex-direction: column;
  gap: 22px;
}

.jd-editor__intro p {
  font-size: 13px;
  line-height: 1.7;
  color: #64748b;
}

.jd-editor__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
}

.jd-editor__full {
  grid-column: 1 / -1;
}

.jd-editor__skills,
.jd-editor__status {
  width: 100%;
}

.jd-content {
  padding: 18px;
  background: #f8fafc;
  border: 1px solid #e5eaf2;
  border-radius: 14px;
}

.jd-content__header {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 14px;
}

.jd-content__header h3 {
  font-size: 14px;
  font-weight: 650;
  color: #0f172a;
}

.jd-content__header p {
  margin-top: 3px;
  font-size: 11.5px;
  color: #94a3b8;
}

.jd-content__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.jd-content__actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.jd-content__empty {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: center;
  justify-content: center;
  min-height: 240px;
  padding: 28px;
  text-align: center;
  background: #ffffff;
  border: 1px dashed #cbd5e1;
  border-radius: 12px;
}

.jd-content__empty-icon {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  color: #2563eb;
  background: #eff6ff;
  border-radius: 14px;
}

.jd-content__empty p {
  font-size: 14px;
  font-weight: 600;
  color: #334155;
}

.jd-content__empty span {
  max-width: 340px;
  font-size: 12px;
  line-height: 1.7;
  color: #94a3b8;
}

.jd-content__typing {
  min-height: 240px;
  padding: 20px;
  margin: 0;
  overflow-x: auto;
  font-family: inherit;
  font-size: 14px;
  line-height: 1.85;
  color: #334155;
  white-space: pre-wrap;
  word-break: break-word;
  background: #ffffff;
  border: 1px solid #e5eaf2;
  border-radius: 12px;
}

.jd-caret {
  display: inline-block;
  width: 2px;
  height: 15px;
  margin-left: 2px;
  vertical-align: -2px;
  background: #2563eb;
  animation: jd-caret-blink 0.8s steps(1) infinite;
}

.jd-content__preview {
  min-height: 240px;
  max-height: 460px;
  padding: 20px;
  overflow-y: auto;
  background: #ffffff;
  border: 1px solid #e5eaf2;
  border-radius: 12px;
}

.jd-editor__footer {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
}

.jd-editor__hint {
  font-size: 11.5px;
  color: #94a3b8;
}

@keyframes jd-caret-blink {
  0%,
  49% {
    opacity: 1;
  }

  50%,
  100% {
    opacity: 0;
  }
}

@media (max-width: 760px) {
  .jd-editor__grid {
    grid-template-columns: 1fr;
  }

  .jd-content__header {
    flex-direction: column;
  }

  .jd-content__actions {
    justify-content: flex-start;
  }
}
</style>

<style>
@media (max-width: 760px) {
  .jd-editor-drawer {
    width: 100% !important;
  }
}
</style>
