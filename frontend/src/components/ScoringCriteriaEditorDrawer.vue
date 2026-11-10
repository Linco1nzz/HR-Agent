<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'

import { Edit, Lock, MagicStick, Plus, Refresh, View } from '@element-plus/icons-vue'
import type { FormInstance, FormRules } from 'element-plus'

import { listJds, getJd } from '@/api/jds'
import {
  createScoringCriteria,
  streamGenerateScoringCriteria,
  updateScoringCriteria,
} from '@/api/scoringCriteria'
import type {
  GenerateScoringCriteriaPayload,
  ScoringCriteria,
  ScoringCriteriaPayload,
  ScoringCriteriaStatus,
  ScoringDimension,
} from '@/api/types'
import JdMarkdown from '@/components/JdMarkdown.vue'

type ContentMode = 'empty' | 'streaming' | 'preview' | 'edit'

interface JdOption {
  id: string
  title: string
}

interface DimensionRow {
  name: string
  score: string
  description: string
}

interface CriteriaFormState {
  title: string
  job_title: string
  content: string
  total_score: string
  status: ScoringCriteriaStatus
  job_description_id: string | null
  conversation_id: string | null
  workflow_type: string
  criteria_data: Record<string, unknown> | null
  meta_data: Record<string, unknown> | null
}

const props = defineProps<{
  modelValue: boolean
  mode: 'create' | 'edit'
  criteria?: ScoringCriteria | null
  presetJdId?: string | null
  /** 从 JD 详情页打开时锁定关联 JD，避免误选到其他岗位 */
  lockJd?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: [criteria: ScoringCriteria]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const isEdit = computed(() => props.mode === 'edit')
const formRef = ref<FormInstance>()
const generating = ref(false)
const saving = ref(false)
const jdLoading = ref(false)
const jdOptions = ref<JdOption[]>([])
const instructions = ref('')
const dimensions = ref<DimensionRow[]>([])
const contentMode = ref<ContentMode>('empty')
const lastAutoTitle = ref('')
let streamController: AbortController | null = null

const createEmptyForm = (): CriteriaFormState => ({
  title: '',
  job_title: '',
  content: '',
  total_score: '100',
  status: 'draft',
  job_description_id: null,
  conversation_id: null,
  workflow_type: 'scoring_criteria_generation',
  criteria_data: null,
  meta_data: null,
})

const form = reactive<CriteriaFormState>(createEmptyForm())

const rules: FormRules = {
  title: [{ required: true, message: '请输入评分标准标题', trigger: 'blur' }],
}

const statusOptions: Array<{ value: ScoringCriteriaStatus; label: string }> = [
  { value: 'draft', label: '草稿' },
  { value: 'generated', label: 'AI 已生成' },
  { value: 'published', label: '已发布' },
  { value: 'archived', label: '已归档' },
]

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '操作失败，请稍后重试'
}

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

function defaultTitle(jdTitle: string): string {
  // 与后端 title 字段的 255 字符上限保持一致
  return `${jdTitle} - 简历评分标准`.slice(0, 255)
}

function toDimensionRows(list: ScoringDimension[] | null | undefined): DimensionRow[] {
  return (list ?? []).map((item) => {
    const score = item.score ?? item.weight
    return {
      name: typeof item.name === 'string' ? item.name : '',
      score: score === undefined || score === null ? '' : String(score),
      description: typeof item.description === 'string' ? item.description : '',
    }
  })
}

function buildDimensions(): ScoringDimension[] | null {
  const rows = dimensions.value
    .map((row) => ({
      name: row.name.trim(),
      score: row.score.trim(),
      description: row.description.trim(),
    }))
    .filter((row) => row.name || row.score || row.description)
  if (!rows.length) return null
  return rows.map((row) => {
    const item: ScoringDimension = {}
    if (row.name) item.name = row.name
    if (row.score) item.score = row.score
    if (row.description) item.description = row.description
    return item
  })
}

function addDimension(): void {
  dimensions.value.push({ name: '', score: '', description: '' })
}

function removeDimension(index: number): void {
  dimensions.value.splice(index, 1)
}

async function ensureJdOption(id: string | null): Promise<void> {
  if (!id || jdOptions.value.some((option) => option.id === id)) return
  try {
    const jd = await getJd(id)
    jdOptions.value = [{ id: jd.id, title: jd.title }, ...jdOptions.value]
  } catch {
    // JD 已被删除时保留原选择，由保存时的后端校验给出明确错误
  }
}

async function loadJdOptions(): Promise<void> {
  jdLoading.value = true
  try {
    const result = await listJds({ page: 1, page_size: 100 })
    jdOptions.value = result.items.map((item) => ({ id: item.id, title: item.title }))
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    jdLoading.value = false
  }
}

function applyJdSelection(value: string | null): void {
  const id = value && value.trim() ? value : null
  form.job_description_id = id
  if (!id) return
  const jd = jdOptions.value.find((option) => option.id === id)
  if (!jd) return
  form.job_title = jd.title
  if (!form.title.trim() || form.title === lastAutoTitle.value) {
    form.title = defaultTitle(jd.title)
    lastAutoTitle.value = form.title
  }
}

async function resetForm(): Promise<void> {
  cancelStream()
  generating.value = false
  instructions.value = ''

  if (isEdit.value && props.criteria) {
    const criteria = props.criteria
    Object.assign(form, {
      title: criteria.title,
      job_title: criteria.job_title ?? '',
      content: criteria.content,
      total_score: criteria.total_score,
      status: criteria.status,
      job_description_id: criteria.job_description_id,
      conversation_id: criteria.conversation_id,
      workflow_type: criteria.workflow_type,
      criteria_data: criteria.criteria_data,
      meta_data: criteria.meta_data,
    })
    dimensions.value = toDimensionRows(criteria.scoring_dimensions)
    contentMode.value = form.content.trim() ? 'preview' : 'empty'
    lastAutoTitle.value = ''
  } else {
    Object.assign(form, createEmptyForm())
    dimensions.value = []
    contentMode.value = 'empty'
    lastAutoTitle.value = ''
  }

  if (props.lockJd) {
    const lockedJdId = props.presetJdId || form.job_description_id
    await ensureJdOption(lockedJdId)
    if (lockedJdId && !isEdit.value) {
      applyJdSelection(lockedJdId)
    } else if (lockedJdId && !form.job_title) {
      const jd = jdOptions.value.find((option) => option.id === lockedJdId)
      if (jd) form.job_title = jd.title
    }
  } else {
    await loadJdOptions()
    const preferredJdId = props.presetJdId || form.job_description_id
    await ensureJdOption(preferredJdId)
    if (preferredJdId && !isEdit.value) {
      applyJdSelection(preferredJdId)
    }
  }

  await nextTick()
  formRef.value?.clearValidate()
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      void resetForm()
    } else {
      cancelStream()
      generating.value = false
    }
  },
)

function toGeneratePayload(): GenerateScoringCriteriaPayload {
  return {
    job_description_id: form.job_description_id ?? '',
    title: form.title.trim() || null,
    total_score: form.total_score.trim() || '100',
    instructions: instructions.value.trim() || null,
  }
}

function toSavePayload(): ScoringCriteriaPayload {
  return {
    title: form.title.trim(),
    job_title: form.job_title.trim() || null,
    content: form.content,
    total_score: form.total_score.trim() || '100',
    status: form.status,
    scoring_dimensions: buildDimensions(),
    job_description_id: form.job_description_id || null,
    conversation_id: form.conversation_id,
    workflow_type: form.workflow_type,
    criteria_data: form.criteria_data,
    meta_data: form.meta_data,
  }
}

async function handleGenerate(): Promise<void> {
  if (generating.value) return
  if (!form.job_description_id) {
    ElMessage.warning('请先选择要生成评分标准的 JD')
    return
  }

  cancelStream()
  const controller = new AbortController()
  streamController = controller
  generating.value = true
  form.content = ''
  contentMode.value = 'streaming'

  try {
    const result = await streamGenerateScoringCriteria(toGeneratePayload(), {
      signal: controller.signal,
      onDelta: (delta) => {
        if (!props.modelValue || controller.signal.aborted) return
        form.content += delta
        contentMode.value = 'streaming'
      },
    })
    if (!props.modelValue) return

    form.title = result.title
    form.job_title = result.job_title ?? form.job_title
    form.content = result.content
    form.total_score = result.total_score
    form.job_description_id = result.job_description_id ?? form.job_description_id
    form.conversation_id = result.conversation_id || null
    form.workflow_type = result.workflow_type || 'scoring_criteria_generation'
    form.criteria_data = result.criteria_data
    form.meta_data = {
      ...(form.meta_data ?? {}),
      source: 'dify',
      task_id: result.task_id || undefined,
      instructions: instructions.value.trim() || undefined,
    }
    form.status = 'generated'
    if (result.scoring_dimensions?.length) {
      dimensions.value = toDimensionRows(result.scoring_dimensions)
    }
    contentMode.value = 'preview'
    ElMessage.success('评分标准已生成，可继续编辑或保存')
  } catch (error) {
    if (isAbortError(error)) return
    ElMessage.error(errorMessage(error))
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
    ElMessage.warning('请先生成或填写评分标准内容')
    return
  }

  saving.value = true
  try {
    const payload = toSavePayload()
    const saved =
      isEdit.value && props.criteria
        ? await updateScoringCriteria(props.criteria.id, payload)
        : await createScoringCriteria(payload)
    ElMessage.success(isEdit.value ? '评分标准已更新' : '评分标准已保存')
    emit('saved', saved)
    visible.value = false
  } catch (error) {
    ElMessage.error(errorMessage(error))
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
    class="criteria-editor-drawer"
    :title="isEdit ? '查看 / 编辑评分标准' : '新建评分标准'"
    size="820px"
    destroy-on-close
  >
    <div class="criteria-editor">
      <div class="criteria-editor__intro">
        <p>
          {{
            isEdit
              ? '修改评分标准的基本信息、评分维度与正文。'
              : lockJd
                ? '让 AI 根据当前 JD 生成 100 分制的简历评分标准，生成时内容会实时出现，确认后再保存。'
                : '选择一份已保存的 JD，让 AI 生成 100 分制的简历评分标准，再按需编辑与保存。'
          }}
        </p>
      </div>

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <div class="criteria-editor__grid">
          <el-form-item label="关联 JD" class="criteria-editor__full">
            <div v-if="lockJd" class="criteria-editor__jd-locked">
              <el-icon :size="18"><Lock /></el-icon>
              <div>
                <strong>{{ form.job_title || '当前 JD' }}</strong>
                <span>评分标准将关联当前 JD，不可更改</span>
              </div>
            </div>
            <el-select
              v-else
              v-model="form.job_description_id"
              class="criteria-editor__control"
              filterable
              clearable
              :loading="jdLoading"
              placeholder="选择一份已保存的 JD"
              @change="applyJdSelection"
            >
              <el-option
                v-for="option in jdOptions"
                :key="option.id"
                :label="option.title"
                :value="option.id"
              />
            </el-select>
            <p v-if="!lockJd" class="criteria-editor__hint">
              评分标准会根据所选 JD 的职位要求、技能与正文生成。
            </p>
          </el-form-item>

          <el-form-item label="标题" prop="title" class="criteria-editor__full">
            <el-input
              v-model="form.title"
              maxlength="255"
              placeholder="例如：高级前端工程师 - 简历评分标准"
            />
          </el-form-item>

          <el-form-item label="职位名称">
            <el-input v-model="form.job_title" maxlength="255" placeholder="自动取自关联 JD" />
          </el-form-item>

          <el-form-item label="总分">
            <el-input v-model="form.total_score" maxlength="20" placeholder="例如：100" />
          </el-form-item>

          <el-form-item v-if="isEdit" label="状态">
            <el-select v-model="form.status" class="criteria-editor__control">
              <el-option
                v-for="option in statusOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
          </el-form-item>

          <el-form-item label="生成要求（可选）" class="criteria-editor__full">
            <el-input
              v-model="instructions"
              type="textarea"
              :rows="3"
              maxlength="2000"
              show-word-limit
              placeholder="例如：重点关注工程化经验、团队协作与业务理解；每个维度给出评分权重。"
            />
          </el-form-item>
        </div>
      </el-form>

      <div class="criteria-editor__generate">
        <div>
          <strong>AI 生成评分标准</strong>
          <p>调用 Dify 简历评价标准流程，正文会边生成边显示，生成后可继续编辑。</p>
        </div>
        <div class="criteria-editor__generate-actions">
          <el-button v-if="generating" @click="handleStopGenerating">停止生成</el-button>
          <el-button
            type="primary"
            :icon="form.content ? Refresh : MagicStick"
            :loading="generating"
            @click="handleGenerate"
          >
            {{ form.content ? '重新生成' : 'AI 生成评分标准' }}
          </el-button>
        </div>
      </div>

      <section class="criteria-content">
        <header class="criteria-content__header">
          <div>
            <h3>评分标准正文</h3>
            <p>AI 生成时内容会实时出现，也可生成后直接编辑。</p>
          </div>
          <div class="criteria-content__actions">
            <template v-if="generating">
              <el-button @click="handleStopGenerating">停止生成</el-button>
            </template>
            <template v-else-if="contentMode === 'empty'">
              <el-button @click="contentMode = 'edit'">直接编辑</el-button>
              <el-button
                type="primary"
                :icon="MagicStick"
                :loading="generating"
                @click="handleGenerate"
              >
                AI 生成
              </el-button>
            </template>
            <template v-else-if="contentMode === 'edit'">
              <el-button :icon="View" @click="handlePreviewContent">预览</el-button>
            </template>
            <template v-else>
              <el-button :icon="Edit" @click="handleEditContent">编辑</el-button>
            </template>
          </div>
        </header>

        <div v-if="contentMode === 'empty'" class="criteria-content__empty">
          <div class="criteria-content__empty-icon">
            <el-icon :size="24"><MagicStick /></el-icon>
          </div>
          <p>还没有评分标准内容</p>
          <span>确认关联 JD 后点击“AI 生成评分标准”，或直接编辑填写。</span>
        </div>

        <pre
          v-else-if="contentMode === 'streaming'"
          class="criteria-content__typing"
        ><span>{{ form.content }}</span><i class="criteria-caret" /></pre>

        <el-input
          v-else-if="contentMode === 'edit'"
          v-model="form.content"
          type="textarea"
          :rows="16"
          resize="vertical"
          placeholder="支持 Markdown，例如：## 评分维度"
        />

        <div v-else class="criteria-content__preview">
          <JdMarkdown :content="form.content" />
        </div>
      </section>

      <section class="criteria-dimensions">
        <header class="criteria-dimensions__header">
          <div>
            <h3>评分维度</h3>
            <p>可选的结构化维度，便于后续简历评分直接复用。</p>
          </div>
          <el-button text type="primary" :icon="Plus" @click="addDimension">添加维度</el-button>
        </header>

        <div v-if="!dimensions.length" class="criteria-dimensions__empty">
          暂无结构化维度，可手动添加，或保留正文中的评分表。
        </div>
        <div v-else class="criteria-dimensions__list">
          <div v-for="(dimension, index) in dimensions" :key="index" class="criteria-dimension-row">
            <span class="criteria-dimension-row__index">{{ index + 1 }}</span>
            <el-input v-model="dimension.name" placeholder="维度名称" maxlength="100" />
            <el-input v-model="dimension.score" placeholder="分值 / 权重" maxlength="20" />
            <el-input v-model="dimension.description" placeholder="评分要点" maxlength="500" />
            <el-button text type="danger" @click="removeDimension(index)">删除</el-button>
          </div>
        </div>
      </section>
    </div>

    <template #footer>
      <div class="criteria-editor__footer">
        <span class="criteria-editor__hint">
          {{ form.content ? `${form.content.length} 字符` : '尚未生成内容' }}
        </span>
        <div>
          <el-button @click="handleClose">取消</el-button>
          <el-button type="primary" :loading="saving" :disabled="generating" @click="handleSave">
            保存评分标准
          </el-button>
        </div>
      </div>
    </template>
  </el-drawer>
</template>

<style scoped>
.criteria-editor {
  display: flex;
  flex-direction: column;
  gap: 22px;
}

.criteria-editor__intro p {
  font-size: 13px;
  line-height: 1.7;
  color: #64748b;
}

.criteria-editor__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
}

.criteria-editor__full {
  grid-column: 1 / -1;
}

.criteria-editor__control {
  width: 100%;
}

.criteria-editor__jd-locked {
  display: flex;
  gap: 10px;
  align-items: center;
  width: 100%;
  padding: 10px 12px;
  color: #1e3a8a;
  background: #f8fbff;
  border: 1px solid #dbeafe;
  border-radius: 10px;
}

.criteria-editor__jd-locked .el-icon {
  flex: none;
  color: #2563eb;
}

.criteria-editor__jd-locked div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.criteria-editor__jd-locked strong {
  overflow: hidden;
  font-size: 13px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.criteria-editor__jd-locked span {
  font-size: 11px;
  color: #64748b;
}

.criteria-editor__hint {
  margin-top: 4px;
  font-size: 11.5px;
  line-height: 1.6;
  color: #94a3b8;
}

.criteria-editor__generate {
  display: flex;
  gap: 16px;
  align-items: center;
  justify-content: space-between;
  padding: 16px 18px;
  background: linear-gradient(135deg, #eff6ff 0%, #f8fbff 100%);
  border: 1px solid #dbeafe;
  border-radius: 14px;
}

.criteria-editor__generate strong {
  font-size: 13.5px;
  font-weight: 650;
  color: #1e3a8a;
}

.criteria-editor__generate p {
  margin-top: 3px;
  font-size: 11.5px;
  color: #64748b;
}

.criteria-editor__generate-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.criteria-editor__generate-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.criteria-content {
  padding: 18px;
  background: #f8fafc;
  border: 1px solid #e5eaf2;
  border-radius: 14px;
}

.criteria-content__header,
.criteria-dimensions__header {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 14px;
}

.criteria-content__header h3,
.criteria-dimensions__header h3 {
  font-size: 14px;
  font-weight: 650;
  color: #0f172a;
}

.criteria-content__header p,
.criteria-dimensions__header p {
  margin-top: 3px;
  font-size: 11.5px;
  color: #94a3b8;
}

.criteria-content__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.criteria-content__actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.criteria-content__empty {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: center;
  justify-content: center;
  min-height: 220px;
  padding: 28px;
  text-align: center;
  background: #ffffff;
  border: 1px dashed #cbd5e1;
  border-radius: 12px;
}

.criteria-content__empty-icon {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  color: #2563eb;
  background: #eff6ff;
  border-radius: 14px;
}

.criteria-content__empty p {
  font-size: 14px;
  font-weight: 600;
  color: #334155;
}

.criteria-content__empty span {
  max-width: 360px;
  font-size: 12px;
  line-height: 1.7;
  color: #94a3b8;
}

.criteria-content__typing {
  min-height: 220px;
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

.criteria-caret {
  display: inline-block;
  width: 2px;
  height: 15px;
  margin-left: 2px;
  vertical-align: -2px;
  background: #2563eb;
  animation: criteria-caret-blink 0.8s steps(1) infinite;
}

@keyframes criteria-caret-blink {
  0%,
  49% {
    opacity: 1;
  }

  50%,
  100% {
    opacity: 0;
  }
}

.criteria-content__preview {
  min-height: 220px;
  max-height: 480px;
  padding: 20px;
  overflow-y: auto;
  background: #ffffff;
  border: 1px solid #e5eaf2;
  border-radius: 12px;
}

.criteria-dimensions {
  padding: 18px;
  background: #ffffff;
  border: 1px solid var(--app-border);
  border-radius: 14px;
}

.criteria-dimensions__empty {
  padding: 18px;
  font-size: 12px;
  color: #94a3b8;
  text-align: center;
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
  border-radius: 12px;
}

.criteria-dimensions__list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.criteria-dimension-row {
  display: grid;
  grid-template-columns: 26px minmax(0, 1.1fr) minmax(0, 0.6fr) minmax(0, 2fr) auto;
  gap: 8px;
  align-items: center;
}

.criteria-dimension-row__index {
  font-size: 11px;
  color: #94a3b8;
  text-align: center;
}

.criteria-editor__footer {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
}

.criteria-editor__footer > div {
  display: flex;
  gap: 8px;
}

@media (max-width: 760px) {
  .criteria-editor__grid {
    grid-template-columns: 1fr;
  }

  .criteria-editor__generate,
  .criteria-content__header,
  .criteria-dimensions__header {
    flex-direction: column;
  }

  .criteria-editor__generate-actions {
    width: 100%;
    justify-content: flex-start;
  }

  .criteria-dimension-row {
    grid-template-columns: 26px 1fr;
  }

  .criteria-dimension-row :deep(.el-input) {
    grid-column: 2;
  }

  .criteria-dimension-row :deep(.el-button) {
    grid-column: 2;
    justify-self: start;
  }
}
</style>

<style>
@media (max-width: 760px) {
  .criteria-editor-drawer {
    width: 100% !important;
  }
}
</style>
