<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import {
  ChatDotRound,
  Download,
  Edit,
  MagicStick,
  Plus,
  Refresh,
  View,
} from '@element-plus/icons-vue'

import {
  createInterviewPlan,
  exportInterviewPlan,
  getInterviewPlan,
  listInterviewPlans,
  streamGenerateInterviewPlan,
  updateInterviewPlan,
} from '@/api/interviewPlans'
import type {
  GenerateInterviewPlanResponse,
  InterviewPlan,
  InterviewPlanExportFormat,
  InterviewPlanListItem,
  ResumeEvaluation,
} from '@/api/types'
import JdMarkdown from '@/components/JdMarkdown.vue'

type PanelMode = 'empty' | 'streaming' | 'preview' | 'edit'

const props = defineProps<{
  resume: ResumeEvaluation
}>()

const plans = ref<InterviewPlanListItem[]>([])
const plansLoading = ref(false)
const selectedId = ref<string | null>(null)
const plan = ref<InterviewPlan | null>(null)
const content = ref('')
const candidateName = ref('')
const candidatePosition = ref('')
const instructions = ref('')
const mode = ref<PanelMode>('empty')
const dirty = ref(false)
const generating = ref(false)
const saving = ref(false)
const exporting = ref(false)
const conversationId = ref('')
const taskId = ref('')

let streamController: AbortController | null = null
let loadToken = 0

const selectedPlan = computed(
  () => plans.value.find((item) => item.id === selectedId.value) ?? null,
)
const hasSavedPlan = computed(() => Boolean(plan.value))

const dateFormatter = new Intl.DateTimeFormat('zh-CN', {
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
})

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : dateFormatter.format(date)
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '操作失败，请稍后重试'
}

function isAbortError(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    'name' in error &&
    (error as { name?: unknown }).name === 'AbortError'
  )
}

function fallbackName(): string {
  const name = props.resume.candidate_name?.trim()
  if (name) return name
  const stem = props.resume.original_filename.replace(/\.[^.]+$/, '').trim()
  return stem || '候选人'
}

function fallbackPosition(): string {
  return props.resume.candidate_position?.trim() || props.resume.job_title || '未指定岗位'
}

function cancelStream(): void {
  if (streamController) {
    streamController.abort()
    streamController = null
  }
}

function resetNewPlan(): void {
  selectedId.value = null
  plan.value = null
  content.value = ''
  candidateName.value = fallbackName()
  candidatePosition.value = fallbackPosition()
  conversationId.value = ''
  taskId.value = ''
  dirty.value = false
  mode.value = 'empty'
}

async function loadPlan(id: string, token?: number): Promise<void> {
  const detail = await getInterviewPlan(id)
  if (token !== undefined && token !== loadToken) return
  plan.value = detail
  selectedId.value = detail.id
  content.value = detail.content
  candidateName.value = detail.candidate_name
  candidatePosition.value = detail.candidate_position
  conversationId.value = detail.conversation_id ?? ''
  dirty.value = false
  mode.value = detail.content.trim() ? 'preview' : 'empty'
}

async function fetchPlans(silent = false): Promise<void> {
  const token = ++loadToken
  if (!silent) plansLoading.value = true
  try {
    const result = await listInterviewPlans({
      resume_evaluation_id: props.resume.id,
      page_size: 50,
    })
    if (token !== loadToken) return
    plans.value = result.items
    const preferred =
      result.items.find((item) => item.id === selectedId.value) ?? result.items[0] ?? null
    if (preferred) {
      await loadPlan(preferred.id, token)
    } else {
      resetNewPlan()
    }
  } catch (error) {
    if (token !== loadToken) return
    plans.value = []
    resetNewPlan()
    ElMessage.error(errorMessage(error))
  } finally {
    if (token === loadToken) plansLoading.value = false
  }
}

async function confirmDiscard(): Promise<boolean> {
  if (!dirty.value) return true
  try {
    await ElMessageBox.confirm('当前修改尚未保存，切换后将丢失。', '确认放弃修改？', {
      confirmButtonText: '放弃修改',
      cancelButtonText: '继续编辑',
      type: 'warning',
    })
    return true
  } catch {
    return false
  }
}

async function handleSelect(id: string): Promise<void> {
  if (!id || id === selectedId.value) return
  if (!(await confirmDiscard())) return
  try {
    await loadPlan(id)
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

async function handleNew(): Promise<void> {
  if (!(await confirmDiscard())) return
  cancelStream()
  generating.value = false
  instructions.value = ''
  resetNewPlan()
}

function markDirty(): void {
  dirty.value = true
}

function handleStop(): void {
  cancelStream()
  generating.value = false
  mode.value = content.value.trim() ? 'preview' : 'empty'
}

async function handleGenerate(): Promise<void> {
  if (generating.value) return
  if (dirty.value && content.value.trim()) {
    try {
      await ElMessageBox.confirm('重新生成会覆盖当前未保存的内容。', '确认重新生成？', {
        confirmButtonText: '重新生成',
        cancelButtonText: '取消',
        type: 'warning',
      })
    } catch {
      return
    }
  }
  cancelStream()
  const previous = {
    content: content.value,
    dirty: dirty.value,
    candidateName: candidateName.value,
    candidatePosition: candidatePosition.value,
  }
  const controller = new AbortController()
  streamController = controller
  generating.value = true
  content.value = ''
  mode.value = 'streaming'
  dirty.value = true

  try {
    const result: GenerateInterviewPlanResponse = await streamGenerateInterviewPlan(
      {
        resume_evaluation_id: props.resume.id,
        instructions: instructions.value.trim() || null,
      },
      {
        signal: controller.signal,
        onDelta: (delta) => {
          if (controller.signal.aborted) return
          content.value += delta
          mode.value = 'streaming'
        },
      },
    )
    if (controller.signal.aborted) return

    content.value = result.content
    candidateName.value = result.candidate_name || fallbackName()
    candidatePosition.value = result.candidate_position || fallbackPosition()
    conversationId.value = result.conversation_id || ''
    taskId.value = result.task_id || ''
    dirty.value = true
    mode.value = 'preview'
    ElMessage.success('面试方案已生成，确认后保存')
  } catch (error) {
    if (isAbortError(error)) return
    if (plan.value) {
      // 重新生成失败时恢复已保存内容，避免界面停留在空白状态
      content.value = previous.content
      candidateName.value = previous.candidateName
      candidatePosition.value = previous.candidatePosition
      mode.value = previous.content.trim() ? 'preview' : 'empty'
      dirty.value = previous.dirty
    } else {
      mode.value = content.value.trim() ? 'preview' : 'empty'
    }
    ElMessage.error(errorMessage(error))
  } finally {
    if (streamController === controller) {
      streamController = null
    }
    generating.value = false
  }
}

async function handleDiscard(): Promise<void> {
  if (!plan.value || generating.value) return
  try {
    await ElMessageBox.confirm('将恢复到最近一次保存的内容。', '确认放弃修改？', {
      confirmButtonText: '放弃修改',
      cancelButtonText: '继续编辑',
      type: 'warning',
    })
  } catch {
    return
  }

  try {
    await loadPlan(plan.value.id)
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

async function handleSave(): Promise<void> {
  if (saving.value || generating.value) return
  if (!content.value.trim()) {
    mode.value = 'edit'
    ElMessage.warning('请先生成或填写面试方案内容')
    return
  }

  saving.value = true
  try {
    const payload = {
      candidate_name: candidateName.value.trim() || fallbackName(),
      candidate_position: candidatePosition.value.trim() || fallbackPosition(),
      content: content.value,
    }
    const savedId = plan.value?.id ?? selectedId.value
    const saved = savedId
      ? await updateInterviewPlan(savedId, payload)
      : await createInterviewPlan({
          ...payload,
          resume_evaluation_id: props.resume.id,
          conversation_id: conversationId.value || null,
          meta_data: {
            source: 'dify',
            task_id: taskId.value || undefined,
            instructions: instructions.value.trim() || undefined,
          },
        })

    plan.value = saved
    selectedId.value = saved.id
    content.value = saved.content
    candidateName.value = saved.candidate_name
    candidatePosition.value = saved.candidate_position
    conversationId.value = saved.conversation_id ?? ''
    dirty.value = false
    mode.value = 'preview'
    ElMessage.success(savedId ? '面试方案已更新' : '面试方案已保存')
    await fetchPlans(true)
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    saving.value = false
  }
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1_000)
}

async function handleExport(command: string | number | object): Promise<void> {
  if (!plan.value) {
    ElMessage.warning('请先保存面试方案再导出')
    return
  }
  if (dirty.value) {
    ElMessage.warning('当前有未保存的修改，请先保存后再导出')
    return
  }

  const format: InterviewPlanExportFormat = command === 'markdown' ? 'markdown' : 'docx'
  exporting.value = true
  try {
    const { blob, filename } = await exportInterviewPlan(plan.value.id, format)
    downloadBlob(blob, filename)
    ElMessage.success('面试方案已开始下载')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    exporting.value = false
  }
}

watch(
  () => props.resume.id,
  () => {
    cancelStream()
    generating.value = false
    plans.value = []
    resetNewPlan()
    void fetchPlans()
  },
)

onMounted(() => {
  resetNewPlan()
  void fetchPlans()
})

onBeforeUnmount(cancelStream)
</script>

<template>
  <section class="interview-panel">
    <header class="interview-panel__header">
      <div class="interview-panel__title">
        <span class="interview-panel__icon">
          <el-icon><ChatDotRound /></el-icon>
        </span>
        <div>
          <h3>面试方案</h3>
          <p>根据当前候选人的简历与 JD 生成面试方案，支持保存、编辑和导出。</p>
        </div>
      </div>

      <div class="interview-panel__actions">
        <el-button v-if="plans.length" :icon="Plus" :disabled="generating" @click="handleNew">
          新建
        </el-button>

        <el-dropdown
          v-if="hasSavedPlan"
          trigger="click"
          :disabled="exporting || dirty || generating"
          @command="handleExport"
        >
          <el-button :icon="Download" :loading="exporting" :disabled="dirty || generating">
            导出
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="docx">导出 Word（.docx）</el-dropdown-item>
              <el-dropdown-item command="markdown">导出 Markdown（.md）</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>

        <el-button v-if="generating" @click="handleStop">停止生成</el-button>
        <el-button
          type="primary"
          :icon="content ? Refresh : MagicStick"
          :loading="generating"
          @click="handleGenerate"
        >
          {{ content ? '重新生成' : 'AI 生成面试方案' }}
        </el-button>
      </div>
    </header>

    <div v-if="plans.length" class="interview-panel__selector">
      <span class="interview-panel__selector-label">已保存方案</span>
      <el-select
        :model-value="selectedId"
        class="interview-panel__select"
        filterable
        placeholder="选择已保存的面试方案"
        :disabled="generating"
        @change="handleSelect"
      >
        <el-option
          v-for="item in plans"
          :key="item.id"
          :label="`${formatDate(item.created_at)} · ${item.content_preview.slice(0, 30)}`"
          :value="item.id"
        />
      </el-select>
      <span v-if="selectedPlan" class="interview-panel__selector-hint">
        更新于 {{ formatDate(selectedPlan.updated_at) }}
      </span>
    </div>

    <div class="interview-panel__instructions">
      <el-input
        v-model="instructions"
        type="textarea"
        :rows="2"
        maxlength="2000"
        show-word-limit
        :disabled="generating"
        placeholder="补充生成要求（可选），例如：重点考察架构能力、团队协作与业务理解。"
      />
    </div>

    <el-skeleton v-if="plansLoading" class="interview-panel__skeleton" :rows="10" animated />

    <div v-else-if="mode === 'empty'" class="interview-panel__empty">
      <div class="interview-panel__empty-icon">
        <el-icon :size="26"><ChatDotRound /></el-icon>
      </div>
      <p>还没有面试方案内容</p>
      <span>确认当前候选人后，点击“AI 生成面试方案”，生成时可实时查看内容。</span>
    </div>

    <pre
      v-else-if="mode === 'streaming'"
      class="interview-panel__typing"
    ><span>{{ content }}</span><i class="interview-caret" /></pre>

    <el-input
      v-else-if="mode === 'edit'"
      v-model="content"
      class="interview-panel__editor"
      type="textarea"
      :rows="22"
      resize="vertical"
      placeholder="支持 Markdown，例如：## 一、考察重点"
      @input="markDirty"
    />

    <div v-else class="interview-panel__preview">
      <JdMarkdown :content="content" />
    </div>

    <footer class="interview-panel__footer">
      <div class="interview-panel__meta">
        <span>{{ candidateName }} · {{ candidatePosition }}</span>
        <span>{{ content.length }} 字符</span>
        <span v-if="dirty" class="interview-panel__dirty">有未保存的修改</span>
        <span v-else-if="plan">已保存</span>
        <span v-else>尚未保存</span>
      </div>
      <div class="interview-panel__footer-actions">
        <el-button v-if="dirty && plan && !generating" text @click="handleDiscard">
          放弃修改
        </el-button>
        <el-button v-if="mode === 'edit'" :icon="View" @click="mode = 'preview'">预览</el-button>
        <el-button v-else-if="mode === 'preview'" :icon="Edit" @click="mode = 'edit'">
          编辑
        </el-button>
        <el-button
          type="primary"
          :loading="saving"
          :disabled="generating || !content.trim()"
          @click="handleSave"
        >
          保存方案
        </el-button>
      </div>
    </footer>
  </section>
</template>

<style scoped>
.interview-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.interview-panel__header {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  justify-content: space-between;
}

.interview-panel__title {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  min-width: 0;
}

.interview-panel__icon {
  display: grid;
  flex: none;
  place-items: center;
  width: 42px;
  height: 42px;
  color: #2563eb;
  background: #eff6ff;
  border-radius: 12px;
}

.interview-panel__title h3 {
  font-size: 15px;
  font-weight: 650;
  color: #0f172a;
}

.interview-panel__title p {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.6;
  color: #94a3b8;
}

.interview-panel__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.interview-panel__actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.interview-panel__selector {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  align-items: center;
  padding: 10px 12px;
  background: #f8fafc;
  border: 1px solid #eef2f7;
  border-radius: 12px;
}

.interview-panel__selector-label {
  font-size: 12px;
  font-weight: 550;
  color: #475569;
  white-space: nowrap;
}

.interview-panel__select {
  width: min(420px, 100%);
}

.interview-panel__selector-hint {
  font-size: 11px;
  color: #94a3b8;
}

.interview-panel__instructions :deep(.el-textarea__inner) {
  font-size: 12.5px;
}

.interview-panel__skeleton {
  padding: 18px;
  background: #ffffff;
  border: 1px solid #e5eaf2;
  border-radius: 14px;
}

.interview-panel__empty {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: center;
  justify-content: center;
  min-height: 280px;
  padding: 28px;
  text-align: center;
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
  border-radius: 14px;
}

.interview-panel__empty-icon {
  display: grid;
  place-items: center;
  width: 52px;
  height: 52px;
  color: #2563eb;
  background: #eff6ff;
  border-radius: 16px;
}

.interview-panel__empty p {
  font-size: 14px;
  font-weight: 600;
  color: #334155;
}

.interview-panel__empty span {
  max-width: 420px;
  font-size: 12px;
  line-height: 1.7;
  color: #94a3b8;
}

.interview-panel__typing {
  min-height: 280px;
  padding: 20px;
  margin: 0;
  overflow-x: auto;
  font-family: inherit;
  font-size: 13.5px;
  line-height: 1.85;
  color: #334155;
  white-space: pre-wrap;
  word-break: break-word;
  background: #ffffff;
  border: 1px solid #e5eaf2;
  border-radius: 14px;
}

.interview-caret {
  display: inline-block;
  width: 2px;
  height: 15px;
  margin-left: 2px;
  vertical-align: -2px;
  background: #2563eb;
  animation: interview-caret-blink 0.8s steps(1) infinite;
}

@keyframes interview-caret-blink {
  0%,
  49% {
    opacity: 1;
  }

  50%,
  100% {
    opacity: 0;
  }
}

.interview-panel__editor :deep(.el-textarea__inner) {
  font-family: inherit;
  font-size: 13px;
  line-height: 1.85;
}

.interview-panel__preview {
  min-height: 280px;
  max-height: 560px;
  padding: 20px;
  overflow-y: auto;
  background: #ffffff;
  border: 1px solid #e5eaf2;
  border-radius: 14px;
}

.interview-panel__footer {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
  padding-top: 4px;
}

.interview-panel__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  font-size: 11px;
  color: #94a3b8;
}

.interview-panel__meta span + span::before {
  margin-right: 8px;
  color: #cbd5e1;
  content: '·';
}

.interview-panel__dirty {
  color: #d97706;
}

.interview-panel__footer-actions {
  display: flex;
  gap: 8px;
}

@media (max-width: 760px) {
  .interview-panel__header {
    flex-direction: column;
  }

  .interview-panel__actions {
    width: 100%;
    justify-content: flex-start;
  }

  .interview-panel__select {
    width: 100%;
  }

  .interview-panel__footer {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
