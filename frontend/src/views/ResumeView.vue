<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  DataAnalysis,
  Document,
  Refresh,
  Search,
  Upload,
  UserFilled,
} from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'

import { listJds } from '@/api/jds'
import {
  getResumeEvaluation,
  listResumeEvaluations,
  updateResumeStatus,
} from '@/api/resumeEvaluations'
import type {
  JobDescriptionListItem,
  ResumeEvaluation,
  ResumeEvaluationListItem,
  ResumeStatus,
} from '@/api/types'
import JdMarkdown from '@/components/JdMarkdown.vue'
import ResumeUploadDialog from '@/components/ResumeUploadDialog.vue'

type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'
type DetailTab = 'result' | 'resume'

const statusMeta: Record<ResumeStatus, { label: string; type: TagType }> = {
  pending: { label: '待复核', type: 'info' },
  interview: { label: '进入面试', type: 'success' },
  rejected: { label: '已淘汰', type: 'danger' },
}

const statusOptions = Object.entries(statusMeta).map(([value, meta]) => ({
  value: value as ResumeStatus,
  label: meta.label,
}))

const router = useRouter()

const records = ref<ResumeEvaluationListItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
const keyword = ref('')
const statusFilter = ref<ResumeStatus | ''>('')
const jdFilter = ref('')
const loading = ref(false)

const jds = ref<JobDescriptionListItem[]>([])
const jdsLoading = ref(true)

const selectedId = ref<string | null>(null)
const selected = ref<ResumeEvaluation | null>(null)
const detailLoading = ref(false)
const detailTab = ref<DetailTab>('result')
const statusSaving = ref(false)

const uploadVisible = ref(false)

const eligibleJds = computed(() => jds.value.filter((jd) => jd.criteria_count > 0))

const aiAnswerIsJson = computed(() => {
  const answer = selected.value?.ai_answer?.trim()
  return Boolean(answer && (answer.startsWith('{') || answer.startsWith('[')))
})

const dateFormatter = new Intl.DateTimeFormat('zh-CN', {
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
})

const fullDateFormatter = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
})

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : dateFormatter.format(date)
}

function formatFullDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : fullDateFormatter.format(date)
}

function formatFileSize(bytes: number | null): string {
  if (!bytes) return '—'
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}

function formatWorkYears(years: number | null): string {
  return years === null || years === undefined ? '—' : `${years} 年`
}

function displayName(record: { candidate_name: string | null; original_filename: string }): string {
  return record.candidate_name?.trim() || record.original_filename
}

function statusOf(status: ResumeStatus): { label: string; type: TagType } {
  return statusMeta[status]
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '加载失败，请稍后重试'
}

function scorePercent(record: { total_score: number | null; max_score: number | null }): number {
  if (record.total_score === null) return 0
  const max = record.max_score && record.max_score > 0 ? record.max_score : 100
  return Math.max(0, Math.min(100, (record.total_score / max) * 100))
}

function scoreTone(record: { total_score: number | null; max_score: number | null }): TagType {
  if (record.total_score === null) return 'info'
  const percent = scorePercent(record)
  if (percent >= 80) return 'success'
  if (percent >= 60) return 'warning'
  return 'danger'
}

function metricPercent(score: number, max: number): number {
  if (!max || max <= 0) return 0
  return Math.max(0, Math.min(100, (score / max) * 100))
}

function metricTone(score: number, max: number): string {
  const percent = metricPercent(score, max)
  if (percent >= 80) return '#16a34a'
  if (percent >= 60) return '#d97706'
  return '#dc2626'
}

async function fetchJds(): Promise<void> {
  jdsLoading.value = true
  try {
    const result = await listJds({ page: 1, page_size: 100 })
    jds.value = result.items
  } catch (error) {
    jds.value = []
    ElMessage.error(errorMessage(error))
  } finally {
    jdsLoading.value = false
  }
}

async function loadDetail(id: string, force = false): Promise<void> {
  if (!force && selectedId.value === id && selected.value) return
  selectedId.value = id
  detailLoading.value = true
  try {
    selected.value = await getResumeEvaluation(id)
  } catch (error) {
    selected.value = null
    ElMessage.error(errorMessage(error))
  } finally {
    detailLoading.value = false
  }
}

async function fetchList(): Promise<void> {
  loading.value = true
  try {
    const result = await listResumeEvaluations({
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value.trim(),
      status: statusFilter.value,
      job_description_id: jdFilter.value,
    })
    records.value = result.items
    total.value = result.total

    const preferred =
      result.items.find((item) => item.id === selectedId.value) ?? result.items[0] ?? null
    if (preferred) {
      await loadDetail(preferred.id, true)
    } else {
      selectedId.value = null
      selected.value = null
    }
  } catch (error) {
    records.value = []
    total.value = 0
    selectedId.value = null
    selected.value = null
    ElMessage.error(errorMessage(error))
  } finally {
    loading.value = false
  }
}

function handleSearch(): void {
  page.value = 1
  void fetchList()
}

function refreshAll(): void {
  void fetchJds()
  void fetchList()
}

function handlePageChange(nextPage: number): void {
  page.value = nextPage
  void fetchList()
}

function openUpload(): void {
  uploadVisible.value = true
}

async function handleUploaded(record: ResumeEvaluation): Promise<void> {
  uploadVisible.value = false
  selectedId.value = record.id
  selected.value = record
  page.value = 1
  keyword.value = ''
  statusFilter.value = ''
  jdFilter.value = ''
  await fetchList()
}

async function handleStatusChange(value: ResumeStatus): Promise<void> {
  if (!selected.value || statusSaving.value) return
  if (value === selected.value.status) return

  statusSaving.value = true
  try {
    const updated = await updateResumeStatus(selected.value.id, value)
    selected.value = updated
    const item = records.value.find((record) => record.id === updated.id)
    if (item) {
      item.status = updated.status
    }
    ElMessage.success('复核状态已更新')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    statusSaving.value = false
  }
}

function goJds(): void {
  void router.push({ name: 'jds' })
}

onMounted(() => {
  void fetchJds()
  void fetchList()
})
</script>

<template>
  <div class="resume-page">
    <section class="resume-header">
      <div>
        <p class="resume-header__eyebrow">人才招聘</p>
        <h1>简历筛选</h1>
        <p class="resume-header__desc">
          上传候选人简历，按 JD 已有的评分标准自动打分，并保留完整简历与评分理由。
        </p>
      </div>
      <el-button type="primary" :icon="Upload" size="large" @click="openUpload">
        上传简历
      </el-button>
    </section>

    <el-alert
      v-if="!jdsLoading && !eligibleJds.length"
      class="resume-notice"
      type="warning"
      show-icon
      :closable="false"
    >
      <template #title>还没有可用于评分的 JD</template>
      简历评分必须使用已生成评分标准的 JD。请先在 JD 管理中生成评分标准。
      <el-button type="primary" link @click="goJds">去 JD 管理</el-button>
    </el-alert>

    <section class="resume-toolbar">
      <el-input
        v-model="keyword"
        class="resume-toolbar__search"
        clearable
        :prefix-icon="Search"
        placeholder="搜索候选人、文件名或岗位"
        @keyup.enter="handleSearch"
        @clear="handleSearch"
      />
      <el-select
        v-model="jdFilter"
        class="resume-toolbar__jd"
        clearable
        filterable
        placeholder="全部 JD"
        :loading="jdsLoading"
        @change="handleSearch"
      >
        <el-option v-for="jd in jds" :key="jd.id" :label="jd.title" :value="jd.id" />
      </el-select>
      <el-select
        v-model="statusFilter"
        class="resume-toolbar__status"
        clearable
        placeholder="全部状态"
        @change="handleSearch"
      >
        <el-option
          v-for="option in statusOptions"
          :key="option.value"
          :label="option.label"
          :value="option.value"
        />
      </el-select>
      <el-button :icon="Refresh" :loading="loading" @click="refreshAll">刷新</el-button>
      <span class="resume-toolbar__count">共 {{ total }} 份简历</span>
    </section>

    <section class="resume-body">
      <aside class="resume-list" aria-label="简历列表">
        <el-skeleton v-if="loading && !records.length" :rows="5" animated />
        <div v-else-if="!records.length" class="resume-list__empty">
          <el-icon :size="30"><UserFilled /></el-icon>
          <p>{{ keyword || statusFilter || jdFilter ? '没有匹配的简历' : '还没有上传过简历' }}</p>
          <el-button
            v-if="!keyword && !statusFilter && !jdFilter"
            type="primary"
            text
            @click="openUpload"
          >
            上传第一份简历
          </el-button>
        </div>

        <button
          v-for="item in records"
          :key="item.id"
          type="button"
          class="resume-item"
          :class="{ 'is-active': item.id === selectedId }"
          @click="loadDetail(item.id)"
        >
          <div class="resume-item__head">
            <h3>{{ displayName(item) }}</h3>
            <el-tag :type="scoreTone(item)" size="small" effect="light" round>
              {{ item.total_score === null ? '未解析' : `${item.total_score} 分` }}
            </el-tag>
          </div>
          <p class="resume-item__position">
            {{ item.candidate_position || item.job_title || '未识别应聘岗位' }}
          </p>
          <p class="resume-item__meta">
            <span>{{ item.job_title || '—' }}</span>
            <span>{{ formatWorkYears(item.work_years) }}</span>
            <span>{{ item.metric_count }} 个维度</span>
          </p>
          <div class="resume-item__footer">
            <el-tag :type="statusOf(item.status).type" size="small" effect="plain" round>
              {{ statusOf(item.status).label }}
            </el-tag>
            <time>{{ formatDate(item.created_at) }}</time>
          </div>
        </button>

        <el-pagination
          v-if="total > pageSize"
          class="resume-list__pagination"
          small
          background
          layout="prev, pager, next"
          :current-page="page"
          :page-size="pageSize"
          :total="total"
          @current-change="handlePageChange"
        />
      </aside>

      <main class="resume-detail-shell">
        <el-skeleton v-if="detailLoading" class="resume-detail-skeleton" :rows="10" animated />

        <article v-else-if="selected" class="resume-detail">
          <header class="resume-detail__header">
            <div class="resume-profile">
              <el-avatar :size="58" class="resume-profile__avatar">
                {{ displayName(selected).slice(0, 1).toUpperCase() }}
              </el-avatar>
              <div class="resume-profile__info">
                <div class="resume-detail__tags">
                  <el-tag :type="statusOf(selected.status).type" effect="light" round>
                    {{ statusOf(selected.status).label }}
                  </el-tag>
                  <el-tag type="info" effect="plain" round>
                    {{ selected.file_type.toUpperCase() }}
                  </el-tag>
                </div>
                <h2>{{ displayName(selected) }}</h2>
                <p>
                  {{ selected.candidate_position || selected.job_title || '未识别应聘岗位' }}
                </p>
              </div>
            </div>

            <div class="resume-detail__actions">
              <el-select
                :model-value="selected.status"
                class="resume-status-select"
                :loading="statusSaving"
                @change="handleStatusChange"
              >
                <el-option
                  v-for="option in statusOptions"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </el-select>
              <el-button :icon="Upload" @click="openUpload">再传一份</el-button>
            </div>
          </header>

          <div class="resume-detail__score">
            <div class="score-summary">
              <span class="score-summary__eyebrow">AI 综合评分</span>
              <div class="score-summary__value">
                <strong>{{ selected.total_score ?? '—' }}</strong>
                <span>/ {{ selected.max_score ?? 100 }}</span>
              </div>
              <el-progress
                :percentage="scorePercent(selected)"
                :stroke-width="8"
                :show-text="false"
                :color="metricTone(selected.total_score ?? 0, selected.max_score ?? 100)"
              />
              <p>AI 评分仅作为初筛参考，请结合简历原文与人工判断复核。</p>
            </div>
            <dl class="resume-meta">
              <div>
                <dt>应聘岗位</dt>
                <dd>{{ selected.candidate_position || selected.job_title || '—' }}</dd>
              </div>
              <div>
                <dt>工作年限</dt>
                <dd>{{ formatWorkYears(selected.work_years) }}</dd>
              </div>
              <div>
                <dt>学历</dt>
                <dd>{{ selected.education_level || '—' }}</dd>
              </div>
              <div>
                <dt>毕业院校</dt>
                <dd>{{ selected.school || '—' }}</dd>
              </div>
              <div>
                <dt>年龄</dt>
                <dd>{{ selected.candidate_age ?? '—' }}</dd>
              </div>
              <div>
                <dt>性别</dt>
                <dd>{{ selected.candidate_gender || '—' }}</dd>
              </div>
            </dl>
          </div>

          <div class="resume-detail__tabs" role="tablist" aria-label="简历详情视图">
            <button
              type="button"
              class="resume-tab"
              :class="{ 'is-active': detailTab === 'result' }"
              role="tab"
              :aria-selected="detailTab === 'result'"
              @click="detailTab = 'result'"
            >
              <el-icon><DataAnalysis /></el-icon>
              评分结果
            </button>
            <button
              type="button"
              class="resume-tab"
              :class="{ 'is-active': detailTab === 'resume' }"
              role="tab"
              :aria-selected="detailTab === 'resume'"
              @click="detailTab = 'resume'"
            >
              <el-icon><Document /></el-icon>
              简历内容
            </button>
          </div>

          <section v-if="detailTab === 'result'" class="resume-tab-panel" role="tabpanel">
            <div v-if="selected.evaluation_metrics.length" class="metric-list">
              <article
                v-for="metric in selected.evaluation_metrics"
                :key="metric.name"
                class="metric-card"
              >
                <header>
                  <h4>{{ metric.name }}</h4>
                  <span>{{ metric.score }} / {{ metric.max || '—' }}</span>
                </header>
                <el-progress
                  :percentage="metricPercent(metric.score, metric.max)"
                  :stroke-width="6"
                  :show-text="false"
                  :color="metricTone(metric.score, metric.max)"
                />
                <p>{{ metric.reason || '暂无评分理由' }}</p>
              </article>
            </div>

            <el-alert v-else type="warning" :closable="false" show-icon title="AI 未返回结构化评分">
              <p>可以在下方查看 AI 原始评价，或重新上传简历再试。</p>
            </el-alert>

            <section v-if="selected.ai_answer" class="resume-section">
              <h3>AI 原始评价</h3>
              <pre v-if="aiAnswerIsJson" class="resume-ai-raw">{{ selected.ai_answer }}</pre>
              <JdMarkdown v-else :content="selected.ai_answer" />
            </section>

            <footer class="resume-detail__footer">
              <span
                >简历：{{ selected.original_filename }} ·
                {{ formatFileSize(selected.file_size) }}</span
              >
              <span>关联 JD：{{ selected.job_title || '—' }}</span>
              <span v-if="selected.scoring_criteria_title">
                评分标准：{{ selected.scoring_criteria_title }}
              </span>
              <span>上传于 {{ formatFullDate(selected.created_at) }}</span>
            </footer>
          </section>

          <section v-else class="resume-tab-panel" role="tabpanel">
            <div class="resume-content-head">
              <h3>简历正文</h3>
              <span
                >{{ selected.original_filename }} · {{ formatFileSize(selected.file_size) }}</span
              >
            </div>
            <pre class="resume-content">{{ selected.resume_content }}</pre>
          </section>
        </article>

        <div v-else class="resume-detail-empty">
          <div class="resume-detail-empty__icon">
            <el-icon :size="30"><UserFilled /></el-icon>
          </div>
          <h2>选择一份简历查看详情</h2>
          <p>上传简历后，这里会展示候选人信息、AI 评分维度与完整简历内容。</p>
          <el-button type="primary" :icon="Upload" @click="openUpload">上传简历</el-button>
        </div>
      </main>
    </section>

    <ResumeUploadDialog
      v-model="uploadVisible"
      :jds="eligibleJds"
      :jds-loading="jdsLoading"
      @uploaded="handleUploaded"
    />
  </div>
</template>

<style scoped>
.resume-page {
  width: 100%;
  max-width: 1440px;
  margin: 0 auto;
}

.resume-header {
  display: flex;
  gap: 20px;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 20px;
}

.resume-header__eyebrow {
  margin-bottom: 6px;
  font-size: 11px;
  font-weight: 650;
  letter-spacing: 1.4px;
  color: #2563eb;
  text-transform: uppercase;
}

.resume-header h1 {
  font-size: clamp(24px, 2.2vw, 30px);
  font-weight: 700;
  letter-spacing: -0.6px;
  color: #0f172a;
}

.resume-header__desc {
  margin-top: 7px;
  font-size: 13px;
  color: #64748b;
}

.resume-notice {
  margin-bottom: 16px;
}

.resume-toolbar {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 12px;
  margin-bottom: 18px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: 14px;
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.02);
}

.resume-toolbar__search {
  max-width: 340px;
}

.resume-toolbar__jd {
  width: 190px;
}

.resume-toolbar__status {
  width: 140px;
}

.resume-toolbar__count {
  margin-left: auto;
  font-size: 12px;
  color: #94a3b8;
  white-space: nowrap;
}

.resume-body {
  display: grid;
  grid-template-columns: minmax(300px, 380px) minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}

.resume-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: calc(100vh - 300px);
  padding-right: 4px;
  overflow-y: auto;
}

.resume-list__empty {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: center;
  justify-content: center;
  min-height: 220px;
  padding: 24px;
  color: #94a3b8;
  text-align: center;
  background: var(--app-surface);
  border: 1px dashed #cbd5e1;
  border-radius: var(--app-radius);
}

.resume-list__empty p {
  font-size: 13px;
}

.resume-item {
  display: block;
  width: 100%;
  padding: 15px 16px;
  text-align: left;
  cursor: pointer;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: 14px;
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease,
    transform 0.18s ease;
}

.resume-item:hover {
  border-color: #bfdbfe;
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.07);
  transform: translateY(-1px);
}

.resume-item.is-active {
  background: linear-gradient(180deg, #f8fbff 0%, #ffffff 100%);
  border-color: #2563eb;
  box-shadow: 0 10px 22px rgba(37, 99, 235, 0.12);
}

.resume-item__head {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  justify-content: space-between;
}

.resume-item__head h3 {
  overflow: hidden;
  font-size: 14px;
  font-weight: 650;
  line-height: 1.45;
  color: #0f172a;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.resume-item__position {
  margin-top: 5px;
  overflow: hidden;
  font-size: 12px;
  color: #475569;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.resume-item__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  margin-top: 6px;
  font-size: 11px;
  color: #94a3b8;
}

.resume-item__meta span + span::before {
  margin-right: 6px;
  color: #cbd5e1;
  content: '·';
}

.resume-item__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 10px;
}

.resume-item__footer time {
  font-size: 10.5px;
  color: #cbd5e1;
}

.resume-list__pagination {
  justify-content: center;
  padding: 6px 0;
}

.resume-detail-shell {
  min-width: 0;
}

.resume-detail-skeleton,
.resume-detail,
.resume-detail-empty {
  padding: 24px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius);
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.02);
}

.resume-detail__header {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  justify-content: space-between;
  padding-bottom: 18px;
  border-bottom: 1px solid #f1f5f9;
}

.resume-profile {
  display: flex;
  gap: 14px;
  align-items: center;
  min-width: 0;
}

.resume-profile__avatar {
  flex: none;
  font-size: 20px;
  font-weight: 700;
  color: #ffffff;
  background: linear-gradient(135deg, #3b82f6, #1d4ed8);
}

.resume-profile__info {
  min-width: 0;
}

.resume-detail__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}

.resume-profile__info h2 {
  font-size: 22px;
  font-weight: 700;
  letter-spacing: -0.4px;
  color: #0f172a;
}

.resume-profile__info p {
  margin-top: 4px;
  font-size: 12px;
  color: #64748b;
}

.resume-detail__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.resume-status-select {
  width: 128px;
}

.resume-detail__score {
  display: grid;
  grid-template-columns: minmax(220px, 0.8fr) minmax(0, 1.2fr);
  gap: 18px;
  padding: 18px 0;
  border-bottom: 1px solid #f1f5f9;
}

.score-summary {
  padding: 16px;
  background: linear-gradient(135deg, #eff6ff 0%, #f8fbff 100%);
  border: 1px solid #dbeafe;
  border-radius: 14px;
}

.score-summary__eyebrow {
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.6px;
  color: #64748b;
  text-transform: uppercase;
}

.score-summary__value {
  display: flex;
  gap: 6px;
  align-items: baseline;
  margin: 6px 0 10px;
}

.score-summary__value strong {
  font-size: 40px;
  font-weight: 750;
  line-height: 1;
  letter-spacing: -1.5px;
  color: #1d4ed8;
}

.score-summary__value span {
  font-size: 13px;
  color: #64748b;
}

.score-summary p {
  margin-top: 10px;
  font-size: 11px;
  line-height: 1.6;
  color: #94a3b8;
}

.resume-meta {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin: 0;
}

.resume-meta dt {
  margin-bottom: 4px;
  font-size: 10.5px;
  color: #94a3b8;
}

.resume-meta dd {
  margin: 0;
  overflow: hidden;
  font-size: 13px;
  font-weight: 550;
  color: #334155;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.resume-detail__tabs {
  display: flex;
  gap: 4px;
  width: fit-content;
  padding: 4px;
  margin-top: 16px;
  background: #f1f5f9;
  border-radius: 12px;
}

.resume-tab {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  padding: 8px 14px;
  font-size: 13px;
  font-weight: 550;
  color: #64748b;
  cursor: pointer;
  background: transparent;
  border: none;
  border-radius: 9px;
  transition:
    color 0.18s ease,
    background 0.18s ease,
    box-shadow 0.18s ease;
}

.resume-tab:hover {
  color: #2563eb;
}

.resume-tab.is-active {
  color: #1d4ed8;
  background: #ffffff;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.08);
}

.resume-tab .el-icon {
  font-size: 15px;
}

.resume-tab-panel {
  padding-top: 18px;
}

.metric-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.metric-card {
  padding: 14px 16px;
  background: #ffffff;
  border: 1px solid #e5eaf2;
  border-radius: 14px;
}

.metric-card header {
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.metric-card h4 {
  font-size: 13.5px;
  font-weight: 650;
  color: #0f172a;
}

.metric-card header span {
  font-size: 12px;
  font-weight: 600;
  color: #475569;
}

.metric-card p {
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.7;
  color: #64748b;
}

.resume-section {
  padding-top: 20px;
}

.resume-section h3 {
  margin-bottom: 10px;
  font-size: 14px;
  font-weight: 650;
  color: #0f172a;
}

.resume-ai-raw {
  max-height: 360px;
  padding: 14px;
  margin: 0;
  overflow: auto;
  font-family: inherit;
  font-size: 12px;
  line-height: 1.8;
  color: #475569;
  white-space: pre-wrap;
  background: #f8fafc;
  border: 1px solid #eef2f7;
  border-radius: 12px;
}

.resume-content-head {
  display: flex;
  gap: 12px;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 10px;
}

.resume-content-head h3 {
  font-size: 14px;
  font-weight: 650;
  color: #0f172a;
}

.resume-content-head span {
  font-size: 11px;
  color: #94a3b8;
}

.resume-content {
  max-height: 620px;
  padding: 16px;
  margin: 0;
  overflow: auto;
  font-family: inherit;
  font-size: 12.5px;
  line-height: 1.9;
  color: #334155;
  white-space: pre-wrap;
  background: #f8fafc;
  border: 1px solid #eef2f7;
  border-radius: 12px;
}

.resume-detail__footer {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  justify-content: space-between;
  padding-top: 18px;
  margin-top: 20px;
  font-size: 11px;
  color: #cbd5e1;
  border-top: 1px solid #f1f5f9;
}

.resume-detail-empty {
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: center;
  justify-content: center;
  min-height: 440px;
  text-align: center;
}

.resume-detail-empty__icon {
  display: grid;
  place-items: center;
  width: 64px;
  height: 64px;
  color: #2563eb;
  background: #eff6ff;
  border-radius: 20px;
}

.resume-detail-empty h2 {
  font-size: 17px;
  font-weight: 650;
  color: #0f172a;
}

.resume-detail-empty p {
  max-width: 360px;
  margin-bottom: 6px;
  font-size: 12.5px;
  line-height: 1.7;
  color: #94a3b8;
}

@media (max-width: 1080px) {
  .resume-detail__score {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 860px) {
  .resume-body {
    grid-template-columns: 1fr;
  }

  .resume-list {
    max-height: none;
    padding-right: 0;
  }

  .resume-toolbar {
    flex-wrap: wrap;
  }

  .resume-toolbar__search {
    flex: 1 1 220px;
    max-width: none;
  }

  .resume-toolbar__count {
    width: 100%;
    margin-left: 0;
  }

  .metric-list {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .resume-detail__tabs {
    width: 100%;
  }

  .resume-tab {
    flex: 1;
    justify-content: center;
  }

  .resume-detail__header {
    flex-direction: column;
  }

  .resume-detail__actions {
    width: 100%;
    justify-content: flex-start;
  }
}

@media (max-width: 560px) {
  .resume-header {
    flex-direction: column;
  }

  .resume-meta {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .resume-detail__footer {
    flex-direction: column;
    gap: 4px;
  }
}
</style>
