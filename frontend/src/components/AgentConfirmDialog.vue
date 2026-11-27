<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'

import { MagicStick, UploadFilled, WarningFilled } from '@element-plus/icons-vue'
import type { FormInstance, FormRules, UploadRequestOptions } from 'element-plus'

import { uploadResume } from '@/api/agent'
import { listJds } from '@/api/jds'
import { listResumeEvaluations } from '@/api/resumeEvaluations'
import type { AgentConfirm, JobDescriptionListItem, ResumeEvaluationListItem } from '@/api/types'

/** 资源类型的中文名。 */
const RESOURCE_LABELS: Record<string, string> = {
  jd: 'JD',
  scoring_criteria: '评分标准',
  interview_plan: '面试方案',
}

const props = defineProps<{
  modelValue: boolean
  pending?: AgentConfirm | null
  /** 确认请求提交中。 */
  confirming?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  confirm: [params?: Record<string, unknown>]
  cancel: []
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const formRef = ref<FormInstance>()
const uploadLoading = ref(false)
const optionsLoading = ref(false)

const jds = ref<JobDescriptionListItem[]>([])
const resumes = ref<ResumeEvaluationListItem[]>([])

/** save/edit 时保留未编辑的字段（正文等）原样提交。 */
const baseData = ref<Record<string, unknown>>({})
const resourceId = ref('')

const form = reactive({
  title: '',
  department: '',
  location: '',
  salary_range: '',
  experience_level: '',
  education: '',
  job_type: '',
  skills: [] as string[],
  requirements: '',
  job_description_id: '',
  resume_source: 'existing' as 'existing' | 'upload',
  resume_evaluation_id: '',
  upload_id: '',
  upload_filename: '',
  upload_chars: 0,
  total_score: '',
  candidate_name: '',
  candidate_position: '',
})

const pendingArgs = computed<Record<string, unknown>>(() => props.pending?.args ?? {})
const tool = computed(() => props.pending?.tool ?? '')
const isDelete = computed(() => tool.value === 'delete_resource')
const isGenerateJd = computed(() => tool.value === 'generate_jd')
const isScoreResume = computed(() => tool.value === 'score_resume')

/** save_resource / edit_resource：展示可编辑的关键字段。 */
const isResourceForm = computed(
  () => tool.value === 'save_resource' || tool.value === 'edit_resource',
)
/** 只有后端标记 editable 的确认卡片才允许改参数；删除恒为只读。 */
const isEditable = computed(() => Boolean(props.pending?.editable) && !isDelete.value)

const resourceType = computed(() => {
  const resource = pendingArgs.value.resource
  return typeof resource === 'string' ? resource : ''
})
const resourceLabel = computed(() => RESOURCE_LABELS[resourceType.value] ?? '资源')

const argsText = computed(() => JSON.stringify(props.pending?.args ?? {}, null, 2))

function asText(value: unknown): string {
  if (value === null || value === undefined) return ''
  return typeof value === 'string' ? value : String(value)
}

function asRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return {}
  return { ...(value as Record<string, unknown>) }
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is string => typeof item === 'string')
}

function nullableText(value: string): string | null {
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '操作失败，请稍后重试'
}

function resetForm(): void {
  form.title = ''
  form.department = ''
  form.location = ''
  form.salary_range = ''
  form.experience_level = ''
  form.education = ''
  form.job_type = ''
  form.skills = []
  form.requirements = ''
  form.job_description_id = ''
  form.resume_source = 'existing'
  form.resume_evaluation_id = ''
  form.upload_id = ''
  form.upload_filename = ''
  form.upload_chars = 0
  form.total_score = ''
  form.candidate_name = ''
  form.candidate_position = ''
  baseData.value = {}
  resourceId.value = ''
  void nextTick(() => formRef.value?.clearValidate())
}

/** 用当前 pending_confirm 的参数填充表单。 */
function syncFromPending(): void {
  resetForm()
  const pending = props.pending
  if (!pending) return
  const args = pending.args

  if (pending.tool === 'generate_jd') {
    form.title = asText(args.title)
    form.department = asText(args.department)
    form.location = asText(args.location)
    form.salary_range = asText(args.salary_range)
    form.experience_level = asText(args.experience_level)
    form.education = asText(args.education)
    form.job_type = asText(args.job_type)
    form.skills = asStringArray(args.skills)
    form.requirements = asText(args.requirements)
    return
  }

  if (pending.tool === 'score_resume') {
    form.job_description_id = asText(args.job_description_id)
    const resumeId = asText(args.resume_evaluation_id)
    const uploadId = asText(args.upload_id)
    if (!resumeId && uploadId) {
      form.resume_source = 'upload'
      form.upload_id = uploadId
    } else {
      form.resume_source = 'existing'
      form.resume_evaluation_id = resumeId
    }
    return
  }

  if (pending.tool === 'save_resource' || pending.tool === 'edit_resource') {
    baseData.value = asRecord(args.data)
    if (pending.tool === 'edit_resource') resourceId.value = asText(args.resource_id)
    if (resourceType.value === 'jd') {
      form.title = asText(baseData.value.title)
      form.department = asText(baseData.value.department)
    } else if (resourceType.value === 'scoring_criteria') {
      form.title = asText(baseData.value.title)
      form.total_score = asText(baseData.value.total_score)
    } else if (resourceType.value === 'interview_plan') {
      form.candidate_name = asText(baseData.value.candidate_name)
      form.candidate_position = asText(baseData.value.candidate_position)
    }
    return
  }

  if (pending.tool === 'delete_resource') {
    resourceId.value = asText(args.resource_id)
  }
}

async function fetchOptions(): Promise<void> {
  optionsLoading.value = true
  try {
    const [jdResult, resumeResult] = await Promise.all([
      listJds({ page: 1, page_size: 100 }),
      listResumeEvaluations({ page: 1, page_size: 100 }),
    ])
    jds.value = jdResult.items
    resumes.value = resumeResult.items
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    optionsLoading.value = false
  }
}

function resumeOptionLabel(resume: ResumeEvaluationListItem): string {
  const name = resume.candidate_name?.trim() || resume.original_filename
  return resume.candidate_position ? `${name} · ${resume.candidate_position}` : name
}

function validateResumeSource(
  _rule: unknown,
  _value: unknown,
  callback: (error?: string | Error) => void,
): void {
  if (form.resume_source === 'upload') {
    if (!form.upload_id) {
      callback(new Error('请先上传简历文件'))
      return
    }
  } else if (!form.resume_evaluation_id) {
    callback(new Error('请选择已上传的简历'))
    return
  }
  callback()
}

const rules = computed<FormRules>(() => {
  if (isGenerateJd.value) {
    return { title: [{ required: true, message: '请输入职位名称', trigger: 'blur' }] }
  }
  if (isScoreResume.value) {
    return {
      job_description_id: [{ required: true, message: '请选择用于评分的 JD', trigger: 'change' }],
      resume_evaluation_id: [{ validator: validateResumeSource, trigger: 'change' }],
    }
  }
  if (isResourceForm.value) {
    if (resourceType.value === 'interview_plan') {
      return { candidate_name: [{ required: true, message: '请输入候选人姓名', trigger: 'blur' }] }
    }
    if (resourceType.value === 'jd' || resourceType.value === 'scoring_criteria') {
      return { title: [{ required: true, message: '请输入标题', trigger: 'blur' }] }
    }
  }
  return {}
})

/** 简历来源切换：已上传简历与表单内上传二者只能留一个。 */
watch(
  () => form.resume_source,
  (source) => {
    if (source === 'existing') {
      form.upload_id = ''
      form.upload_filename = ''
      form.upload_chars = 0
    } else {
      form.resume_evaluation_id = ''
    }
  },
)

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    syncFromPending()
    if (props.pending?.tool === 'score_resume') void fetchOptions()
  },
)

watch(
  () => props.pending,
  (pending) => {
    if (pending && props.modelValue) syncFromPending()
  },
)

async function handleUpload(options: UploadRequestOptions): Promise<void> {
  uploadLoading.value = true
  try {
    const result = await uploadResume(options.file)
    form.upload_id = result.upload_id
    form.upload_filename = result.filename
    form.upload_chars = result.resume_chars
    form.resume_evaluation_id = ''
    ElMessage.success('简历已上传并解析，确认后开始评分')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    uploadLoading.value = false
  }
}

function clearUpload(): void {
  form.upload_id = ''
  form.upload_filename = ''
  form.upload_chars = 0
}

function buildParams(pending: AgentConfirm): Record<string, unknown> | undefined {
  // 只读确认不提交 params，后端沿用原参数
  if (!isEditable.value) return undefined

  if (pending.tool === 'generate_jd') {
    return {
      title: form.title.trim(),
      department: nullableText(form.department),
      location: nullableText(form.location),
      salary_range: nullableText(form.salary_range),
      experience_level: nullableText(form.experience_level),
      education: nullableText(form.education),
      job_type: nullableText(form.job_type),
      skills: form.skills.length ? [...form.skills] : null,
      requirements: nullableText(form.requirements),
    }
  }

  if (pending.tool === 'score_resume') {
    // 两个字段都显式提交：覆盖原始参数，避免合并后同时存在
    return {
      job_description_id: form.job_description_id,
      resume_evaluation_id: form.resume_source === 'existing' ? form.resume_evaluation_id : null,
      upload_id: form.resume_source === 'upload' ? form.upload_id : null,
    }
  }

  if (pending.tool === 'save_resource' || pending.tool === 'edit_resource') {
    const data = { ...baseData.value }
    if (resourceType.value === 'jd') {
      data.title = form.title.trim()
      data.department = nullableText(form.department)
    } else if (resourceType.value === 'scoring_criteria') {
      data.title = form.title.trim()
      data.total_score = form.total_score.trim() || '100'
    } else if (resourceType.value === 'interview_plan') {
      data.candidate_name = form.candidate_name.trim()
      data.candidate_position = form.candidate_position.trim()
    }
    const params: Record<string, unknown> = { resource: pending.args.resource, data }
    if (pending.tool === 'edit_resource') params.resource_id = pending.args.resource_id
    return params
  }

  // delete_resource 等只读确认：不提交 params，后端沿用原参数
  return undefined
}

async function handleConfirm(): Promise<void> {
  const pending = props.pending
  if (!pending || props.confirming) return

  if (isEditable.value) {
    try {
      await formRef.value?.validate()
    } catch {
      return
    }
  }

  if (isScoreResume.value) {
    if (!form.job_description_id) {
      ElMessage.warning('请选择用于评分的 JD')
      return
    }
    if (form.resume_source === 'existing' && !form.resume_evaluation_id) {
      ElMessage.warning('请选择已上传的简历')
      return
    }
    if (form.resume_source === 'upload' && !form.upload_id) {
      ElMessage.warning('请先上传简历文件')
      return
    }
  }

  emit('confirm', buildParams(pending))
}
</script>

<template>
  <el-dialog
    v-model="visible"
    width="640px"
    top="7vh"
    append-to-body
    :close-on-click-modal="false"
    :close-on-press-escape="!confirming"
    :show-close="!confirming"
  >
    <template #header>
      <div class="agent-confirm__header">
        <div class="agent-confirm__header-icon" :class="{ 'is-danger': isDelete }">
          <el-icon :size="18">
            <WarningFilled v-if="isDelete" />
            <MagicStick v-else />
          </el-icon>
        </div>
        <div class="agent-confirm__header-text">
          <h3>{{ pending?.name || pending?.tool || '确认操作' }}</h3>
          <p>{{ pending?.summary }}</p>
        </div>
      </div>
    </template>

    <el-alert
      v-if="isDelete"
      class="agent-confirm__alert"
      type="warning"
      :closable="false"
      show-icon
    >
      删除后该资源将被软删除，确认后立即执行且无法在此撤销。
    </el-alert>

    <el-form
      v-if="isEditable"
      ref="formRef"
      :model="form"
      :rules="rules"
      label-position="top"
      class="agent-confirm__form"
    >
      <!-- 生成 JD：执行前确认参数表单 -->
      <template v-if="isGenerateJd">
        <div class="agent-confirm__grid">
          <el-form-item label="职位名称" prop="title">
            <el-input v-model="form.title" maxlength="255" placeholder="必填" />
          </el-form-item>
          <el-form-item label="所属部门">
            <el-input v-model="form.department" maxlength="100" placeholder="选填" />
          </el-form-item>
          <el-form-item label="工作地点">
            <el-input v-model="form.location" maxlength="100" placeholder="选填" />
          </el-form-item>
          <el-form-item label="薪资范围">
            <el-input v-model="form.salary_range" maxlength="100" placeholder="选填" />
          </el-form-item>
          <el-form-item label="经验要求">
            <el-input v-model="form.experience_level" maxlength="100" placeholder="选填" />
          </el-form-item>
          <el-form-item label="学历要求">
            <el-input v-model="form.education" maxlength="100" placeholder="选填" />
          </el-form-item>
          <el-form-item label="工作类型">
            <el-input v-model="form.job_type" maxlength="100" placeholder="选填，如全职" />
          </el-form-item>
        </div>

        <el-form-item label="技能要求">
          <el-select
            v-model="form.skills"
            class="agent-confirm__full"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="输入后回车添加技能"
          />
        </el-form-item>

        <el-form-item label="职位要求">
          <el-input
            v-model="form.requirements"
            type="textarea"
            maxlength="5000"
            :autosize="{ minRows: 2, maxRows: 5 }"
            placeholder="选填，可补充更具体的要求"
          />
        </el-form-item>
      </template>

      <!-- 简历评分：选 JD + 选已有简历 / 上传新简历 -->
      <template v-else-if="isScoreResume">
        <el-form-item label="用于评分的 JD" prop="job_description_id">
          <el-select
            v-model="form.job_description_id"
            class="agent-confirm__full"
            filterable
            placeholder="请选择 JD"
            :loading="optionsLoading"
          >
            <el-option v-for="jd in jds" :key="jd.id" :label="jd.title" :value="jd.id" />
          </el-select>
        </el-form-item>

        <el-form-item label="简历来源">
          <el-radio-group v-model="form.resume_source">
            <el-radio value="existing">选择已上传简历</el-radio>
            <el-radio value="upload">上传新简历</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item
          v-if="form.resume_source === 'existing'"
          label="已上传简历"
          prop="resume_evaluation_id"
        >
          <el-select
            v-model="form.resume_evaluation_id"
            class="agent-confirm__full"
            filterable
            placeholder="请选择已上传的简历"
            :loading="optionsLoading"
          >
            <el-option
              v-for="resume in resumes"
              :key="resume.id"
              :label="resumeOptionLabel(resume)"
              :value="resume.id"
            />
          </el-select>
        </el-form-item>

        <el-form-item v-else label="上传简历">
          <div class="agent-confirm__upload">
            <el-upload
              :show-file-list="false"
              accept=".pdf,.doc,.docx,.txt"
              :http-request="handleUpload"
            >
              <el-button :loading="uploadLoading" :icon="UploadFilled"> 选择文件并解析 </el-button>
            </el-upload>

            <div v-if="form.upload_id" class="agent-confirm__upload-tip">
              <el-tag size="small" type="success" effect="light" round>
                {{ form.upload_filename || '已上传简历' }}
              </el-tag>
              <span>已解析 {{ form.upload_chars }} 字</span>
              <el-button text size="small" type="danger" @click="clearUpload">移除</el-button>
            </div>
            <span v-else class="agent-confirm__hint">
              支持 PDF / DOC / DOCX / TXT，上传后仅解析文本，确认后才评分
            </span>
          </div>
        </el-form-item>
      </template>

      <!-- 保存 / 编辑资源：只改关键字段，其余原样保留 -->
      <template v-else-if="isResourceForm">
        <div class="agent-confirm__resource">
          <el-tag size="small" type="primary" effect="light" round>{{ resourceLabel }}</el-tag>
          <span v-if="resourceId" class="agent-confirm__resource-id"
            >目标 ID：{{ resourceId }}</span
          >
        </div>

        <div class="agent-confirm__grid">
          <el-form-item
            v-if="resourceType === 'jd' || resourceType === 'scoring_criteria'"
            label="标题"
            prop="title"
          >
            <el-input v-model="form.title" maxlength="255" />
          </el-form-item>
          <el-form-item v-if="resourceType === 'jd'" label="所属部门">
            <el-input v-model="form.department" maxlength="100" placeholder="选填" />
          </el-form-item>
          <el-form-item v-if="resourceType === 'scoring_criteria'" label="总分">
            <el-input v-model="form.total_score" maxlength="20" placeholder="默认 100" />
          </el-form-item>
          <el-form-item
            v-if="resourceType === 'interview_plan'"
            label="候选人姓名"
            prop="candidate_name"
          >
            <el-input v-model="form.candidate_name" maxlength="100" />
          </el-form-item>
          <el-form-item v-if="resourceType === 'interview_plan'" label="应聘职位">
            <el-input v-model="form.candidate_position" maxlength="100" />
          </el-form-item>
        </div>

        <el-alert class="agent-confirm__alert" type="info" :closable="false" show-icon>
          其余字段（正文等内容）按生成结果原样保存。
        </el-alert>
      </template>

      <template v-else>
        <p class="agent-confirm__hint">该操作暂不支持在此编辑参数，确认后按原参数执行。</p>
        <pre class="agent-confirm__args">{{ argsText }}</pre>
      </template>
    </el-form>

    <!-- 删除：只读展示，只能取消 / 确认删除 -->
    <div v-else-if="isDelete" class="agent-confirm__readonly">
      <div class="agent-confirm__readonly-row">
        <span>操作</span>
        <strong>删除{{ resourceLabel }}（软删除）</strong>
      </div>
      <div class="agent-confirm__readonly-row">
        <span>目标资源</span>
        <strong>{{ resourceLabel }} · {{ resourceId || '—' }}</strong>
      </div>
      <p class="agent-confirm__hint">只读确认：参数不可修改，确认后立即执行删除。</p>
    </div>

    <div v-else class="agent-confirm__readonly">
      <p class="agent-confirm__hint">该操作暂不支持在前端编辑参数，确认后按原参数执行。</p>
      <pre class="agent-confirm__args">{{ argsText }}</pre>
    </div>

    <template #footer>
      <div class="agent-confirm__footer">
        <!-- 删除卡片按要求只保留「取消 / 确认删除」，不提供暂缓入口 -->
        <el-button v-if="!isDelete" text :disabled="confirming" @click="visible = false">
          暂不处理
        </el-button>
        <span v-else class="agent-confirm__footer-gap" />
        <div class="agent-confirm__footer-actions">
          <el-button :disabled="confirming" @click="emit('cancel')">取消任务</el-button>
          <el-button
            type="primary"
            :loading="confirming"
            :disabled="!pending"
            @click="handleConfirm"
          >
            {{ isDelete ? '确认删除' : '确认执行' }}
          </el-button>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.agent-confirm__header {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding-right: 24px;
}

.agent-confirm__header-icon {
  display: grid;
  flex: none;
  place-items: center;
  width: 38px;
  height: 38px;
  color: #2563eb;
  background: #eff6ff;
  border-radius: 11px;
}

.agent-confirm__header-icon.is-danger {
  color: #dc2626;
  background: #fee2e2;
}

.agent-confirm__header-text {
  min-width: 0;
}

.agent-confirm__header-text h3 {
  overflow: hidden;
  font-size: 15px;
  font-weight: 650;
  color: #0f172a;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-confirm__header-text p {
  margin-top: 3px;
  font-size: 11.5px;
  line-height: 1.6;
  color: #94a3b8;
}

.agent-confirm__alert {
  margin-bottom: 12px;
}

.agent-confirm__form :deep(.el-form-item) {
  margin-bottom: 14px;
}

.agent-confirm__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 14px;
}

.agent-confirm__full {
  width: 100%;
}

.agent-confirm__resource {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 12px;
}

.agent-confirm__resource-id {
  overflow: hidden;
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 11px;
  color: #94a3b8;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-confirm__upload {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.agent-confirm__upload-tip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  font-size: 11.5px;
  color: #64748b;
}

.agent-confirm__hint {
  font-size: 11.5px;
  line-height: 1.7;
  color: #94a3b8;
}

.agent-confirm__readonly {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 16px;
  background: #f8fafc;
  border: 1px solid #eef2f7;
  border-radius: 12px;
}

.agent-confirm__readonly-row {
  display: flex;
  gap: 12px;
  align-items: baseline;
  font-size: 12.5px;
}

.agent-confirm__readonly-row span {
  flex: none;
  width: 64px;
  font-size: 11.5px;
  color: #94a3b8;
}

.agent-confirm__readonly-row strong {
  font-weight: 600;
  color: #1e293b;
  overflow-wrap: anywhere;
}

.agent-confirm__args {
  max-height: 240px;
  padding: 12px 14px;
  margin: 0;
  overflow: auto;
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 11px;
  line-height: 1.7;
  color: #334155;
  white-space: pre-wrap;
  background: #f8fafc;
  border: 1px solid #eef2f7;
  border-radius: 10px;
}

.agent-confirm__footer {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
}

.agent-confirm__footer-gap {
  flex: 1;
}

.agent-confirm__footer-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

@media (max-width: 720px) {
  .agent-confirm__grid {
    grid-template-columns: 1fr;
  }
}
</style>
