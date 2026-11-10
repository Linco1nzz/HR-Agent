<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  Document,
  DocumentChecked,
  Edit,
  MagicStick,
  Plus,
  Refresh,
  Search,
} from '@element-plus/icons-vue'

import { getJd, listJds } from '@/api/jds'
import { getScoringCriteria, listScoringCriteria } from '@/api/scoringCriteria'
import type {
  JdStatus,
  JobDescription,
  JobDescriptionListItem,
  ScoringCriteria,
  ScoringCriteriaListItem,
  ScoringCriteriaStatus,
} from '@/api/types'
import JdEditorDrawer from '@/components/JdEditorDrawer.vue'
import JdMarkdown from '@/components/JdMarkdown.vue'
import ScoringCriteriaEditorDrawer from '@/components/ScoringCriteriaEditorDrawer.vue'

type TagType = 'primary' | 'success' | 'warning' | 'info'
type DetailTab = 'jd' | 'criteria'

const statusMeta: Record<JdStatus, { label: string; type: TagType }> = {
  draft: { label: '草稿', type: 'info' },
  generated: { label: 'AI 已生成', type: 'primary' },
  published: { label: '已发布', type: 'success' },
  archived: { label: '已归档', type: 'warning' },
}

const criteriaStatusMeta: Record<ScoringCriteriaStatus, { label: string; type: TagType }> = {
  draft: { label: '草稿', type: 'info' },
  generated: { label: 'AI 已生成', type: 'primary' },
  published: { label: '已发布', type: 'success' },
  archived: { label: '已归档', type: 'warning' },
}

const statusOptions = Object.entries(statusMeta).map(([value, meta]) => ({
  value: value as JdStatus,
  label: meta.label,
}))

const jds = ref<JobDescriptionListItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
const keyword = ref('')
const statusFilter = ref<JdStatus | ''>('')
const loading = ref(false)

const selectedId = ref<string | null>(null)
const selected = ref<JobDescription | null>(null)
const detailLoading = ref(false)
const detailTab = ref<DetailTab>('jd')

const drawerVisible = ref(false)
const drawerMode = ref<'create' | 'edit'>('create')
const editingJd = ref<JobDescription | null>(null)

const criteriaList = ref<ScoringCriteriaListItem[]>([])
const criteriaTotal = ref(0)
const criteriaLoading = ref(false)
const criteriaJdId = ref<string | null>(null)
const criteriaDrawerVisible = ref(false)
const criteriaDrawerMode = ref<'create' | 'edit'>('create')
const editingCriteria = ref<ScoringCriteria | null>(null)
const criteriaOpeningId = ref<string | null>(null)

let criteriaRequestId = 0

const criteriaPresetJdId = computed(() => selected.value?.id ?? null)

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

const detailMeta = computed(() => {
  const jd = selected.value
  if (!jd) return []
  return [
    { label: '所属部门', value: jd.department || '—' },
    { label: '工作地点', value: jd.location || '—' },
    { label: '薪资范围', value: jd.salary_range || '—' },
    { label: '经验等级', value: jd.experience_level || '—' },
    { label: '学历要求', value: jd.education || '—' },
    { label: '工作类型', value: jd.job_type || '—' },
  ]
})

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : dateFormatter.format(date)
}

function formatFullDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : fullDateFormatter.format(date)
}

function statusOf(status: JdStatus): { label: string; type: TagType } {
  return statusMeta[status]
}

function criteriaStatusOf(status: ScoringCriteriaStatus): { label: string; type: TagType } {
  return criteriaStatusMeta[status]
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '加载失败，请稍后重试'
}

function resetCriteria(): void {
  criteriaRequestId += 1
  criteriaJdId.value = null
  criteriaList.value = []
  criteriaTotal.value = 0
  criteriaLoading.value = false
}

function syncCriteriaCount(jdId: string, count: number): void {
  const item = jds.value.find((jd) => jd.id === jdId)
  if (item) item.criteria_count = count
}

async function loadCriteria(jdId: string, force = false): Promise<void> {
  if (!force && criteriaJdId.value === jdId) return

  const isNewJd = criteriaJdId.value !== jdId
  const requestId = ++criteriaRequestId
  criteriaJdId.value = jdId
  criteriaLoading.value = true
  if (isNewJd) {
    criteriaList.value = []
    criteriaTotal.value = 0
  }

  try {
    const result = await listScoringCriteria({
      job_description_id: jdId,
      page: 1,
      page_size: 100,
    })
    if (requestId !== criteriaRequestId) return
    criteriaList.value = result.items
    criteriaTotal.value = result.total
    syncCriteriaCount(jdId, result.total)
  } catch (error) {
    if (requestId !== criteriaRequestId) return
    if (isNewJd) {
      criteriaList.value = []
      criteriaTotal.value = 0
    }
    if (detailTab.value === 'criteria') {
      ElMessage.error(errorMessage(error))
    } else {
      // 用户尚未打开评分标准标签时不打扰，切到该标签时再重试
      criteriaJdId.value = null
    }
  } finally {
    if (requestId === criteriaRequestId) {
      criteriaLoading.value = false
    }
  }
}

async function loadDetail(id: string, force = false): Promise<void> {
  if (!force && selectedId.value === id && selected.value) return
  selectedId.value = id
  detailLoading.value = true
  try {
    selected.value = await getJd(id)
    void loadCriteria(id)
  } catch (error) {
    selected.value = null
    resetCriteria()
    ElMessage.error(errorMessage(error))
  } finally {
    detailLoading.value = false
  }
}

async function fetchList(): Promise<void> {
  loading.value = true
  try {
    const result = await listJds({
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value.trim(),
      status: statusFilter.value,
    })
    jds.value = result.items
    total.value = result.total

    const preferred =
      result.items.find((item) => item.id === selectedId.value) ?? result.items[0] ?? null
    if (preferred) {
      await loadDetail(preferred.id, true)
    } else {
      selectedId.value = null
      selected.value = null
      resetCriteria()
    }
  } catch (error) {
    jds.value = []
    total.value = 0
    selectedId.value = null
    selected.value = null
    resetCriteria()
    ElMessage.error(errorMessage(error))
  } finally {
    loading.value = false
  }
}

function handleSearch(): void {
  page.value = 1
  void fetchList()
}

function handlePageChange(nextPage: number): void {
  page.value = nextPage
  void fetchList()
}

function openCreate(): void {
  drawerMode.value = 'create'
  editingJd.value = null
  drawerVisible.value = true
}

function openEdit(): void {
  if (!selected.value) return
  drawerMode.value = 'edit'
  editingJd.value = selected.value
  drawerVisible.value = true
}

function showCriteriaTab(): void {
  detailTab.value = 'criteria'
  const jdId = selected.value?.id
  if (jdId && criteriaJdId.value !== jdId && !criteriaLoading.value) {
    void loadCriteria(jdId, true)
  }
}

function openCriteriaCreate(): void {
  if (!selected.value) return
  criteriaDrawerMode.value = 'create'
  editingCriteria.value = null
  criteriaDrawerVisible.value = true
}

async function openCriteriaEdit(item: ScoringCriteriaListItem): Promise<void> {
  if (criteriaOpeningId.value) return
  criteriaOpeningId.value = item.id
  try {
    const detail = await getScoringCriteria(item.id)
    // 加载期间用户可能已切换到其他 JD，避免打开不属于当前 JD 的编辑器
    if (selected.value?.id !== item.job_description_id) return
    editingCriteria.value = detail
    criteriaDrawerMode.value = 'edit'
    criteriaDrawerVisible.value = true
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    criteriaOpeningId.value = null
  }
}

async function handleCriteriaSaved(criteria: ScoringCriteria): Promise<void> {
  criteriaDrawerVisible.value = false
  const jdId = criteria.job_description_id ?? selected.value?.id
  if (jdId) {
    await loadCriteria(jdId, true)
  }
}

async function handleSaved(jd: JobDescription): Promise<void> {
  drawerVisible.value = false
  if (drawerMode.value === 'create') {
    // 新建后清空筛选，避免新 JD 被当前筛选条件隐藏
    keyword.value = ''
    statusFilter.value = ''
  }
  selectedId.value = jd.id
  page.value = 1
  await fetchList()
}

onMounted(() => {
  void fetchList()
})
</script>

<template>
  <div class="jd-page">
    <section class="jd-header">
      <div>
        <p class="jd-header__eyebrow">人才招聘</p>
        <h1>JD 管理</h1>
        <p class="jd-header__desc">
          集中管理职位描述与简历评分标准，支持 AI 生成、在线编辑与状态跟踪。
        </p>
      </div>
      <el-button type="primary" :icon="Plus" size="large" @click="openCreate"> 新建 JD </el-button>
    </section>

    <section class="jd-toolbar">
      <el-input
        v-model="keyword"
        class="jd-toolbar__search"
        clearable
        :prefix-icon="Search"
        placeholder="搜索职位名称、部门或正文"
        @keyup.enter="handleSearch"
        @clear="handleSearch"
      />
      <el-select
        v-model="statusFilter"
        class="jd-toolbar__status"
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
      <el-button :icon="Refresh" :loading="loading" @click="fetchList">刷新</el-button>
      <span class="jd-toolbar__count">共 {{ total }} 个 JD</span>
    </section>

    <section class="jd-body">
      <aside class="jd-list" aria-label="JD 列表">
        <el-skeleton v-if="loading && !jds.length" :rows="5" animated />
        <div v-else-if="!jds.length" class="jd-list__empty">
          <el-icon :size="30"><Document /></el-icon>
          <p>{{ keyword || statusFilter ? '没有匹配的 JD' : '还没有保存的 JD' }}</p>
          <el-button v-if="!keyword && !statusFilter" type="primary" text @click="openCreate">
            创建第一个 JD
          </el-button>
        </div>
        <button
          v-for="item in jds"
          :key="item.id"
          type="button"
          class="jd-item"
          :class="{ 'is-active': item.id === selectedId }"
          @click="loadDetail(item.id)"
        >
          <div class="jd-item__head">
            <h3>{{ item.title }}</h3>
            <el-tag :type="statusOf(item.status).type" size="small" effect="light" round>
              {{ statusOf(item.status).label }}
            </el-tag>
          </div>
          <p class="jd-item__meta">
            <span v-if="item.department">{{ item.department }}</span>
            <span v-if="item.location">{{ item.location }}</span>
            <span v-if="item.experience_level">{{ item.experience_level }}</span>
            <span v-if="item.criteria_count" class="jd-item__criteria">
              评分标准 {{ item.criteria_count }}
            </span>
          </p>
          <p class="jd-item__preview">{{ item.content_preview }}</p>
          <div class="jd-item__footer">
            <div class="jd-item__skills">
              <span v-for="skill in (item.skills ?? []).slice(0, 3)" :key="skill">{{ skill }}</span>
              <span v-if="(item.skills?.length ?? 0) > 3" class="jd-item__more">
                +{{ (item.skills?.length ?? 0) - 3 }}
              </span>
            </div>
            <time>{{ formatDate(item.updated_at) }}</time>
          </div>
        </button>

        <el-pagination
          v-if="total > pageSize"
          class="jd-list__pagination"
          small
          background
          layout="prev, pager, next"
          :current-page="page"
          :page-size="pageSize"
          :total="total"
          @current-change="handlePageChange"
        />
      </aside>

      <main class="jd-detail-shell">
        <el-skeleton v-if="detailLoading" class="jd-detail-skeleton" :rows="10" animated />

        <article v-else-if="selected" class="jd-detail">
          <header class="jd-detail__header">
            <div>
              <div class="jd-detail__tags">
                <el-tag :type="statusOf(selected.status).type" effect="light" round>
                  {{ statusOf(selected.status).label }}
                </el-tag>
                <el-tag type="info" effect="plain" round>
                  {{
                    selected.workflow_type === 'jd_generation'
                      ? 'AI JD 流程'
                      : selected.workflow_type
                  }}
                </el-tag>
              </div>
              <h2>{{ selected.title }}</h2>
              <p class="jd-detail__updated">更新于 {{ formatFullDate(selected.updated_at) }}</p>
            </div>
            <div class="jd-detail__actions">
              <el-button type="primary" plain :icon="DocumentChecked" @click="showCriteriaTab">
                评分标准
              </el-button>
              <el-button type="primary" plain :icon="Edit" @click="openEdit">编辑</el-button>
            </div>
          </header>

          <div class="jd-detail__tabs" role="tablist" aria-label="JD 详情视图">
            <button
              type="button"
              class="jd-tab"
              :class="{ 'is-active': detailTab === 'jd' }"
              role="tab"
              :aria-selected="detailTab === 'jd'"
              @click="detailTab = 'jd'"
            >
              <el-icon><Document /></el-icon>
              职位描述
            </button>
            <button
              type="button"
              class="jd-tab"
              :class="{ 'is-active': detailTab === 'criteria' }"
              role="tab"
              :aria-selected="detailTab === 'criteria'"
              @click="showCriteriaTab"
            >
              <el-icon><DocumentChecked /></el-icon>
              简历评分标准
              <span v-if="criteriaTotal" class="jd-tab__badge">{{ criteriaTotal }}</span>
            </button>
          </div>

          <div v-if="detailTab === 'jd'" class="jd-tab-panel" role="tabpanel" aria-label="职位描述">
            <dl class="jd-detail__meta">
              <div v-for="item in detailMeta" :key="item.label">
                <dt>{{ item.label }}</dt>
                <dd>{{ item.value }}</dd>
              </div>
            </dl>

            <section v-if="selected.skills?.length" class="jd-detail__section">
              <h3>技能要求</h3>
              <div class="jd-detail__skills">
                <el-tag v-for="skill in selected.skills" :key="skill" effect="plain" round>
                  {{ skill }}
                </el-tag>
              </div>
            </section>

            <section class="jd-detail__section">
              <h3>JD 内容</h3>
              <JdMarkdown :content="selected.content" />
            </section>

            <section v-if="selected.requirements" class="jd-detail__section">
              <h3>职位要求</h3>
              <p class="jd-detail__requirements">{{ selected.requirements }}</p>
            </section>

            <footer class="jd-detail__footer">
              <span>创建于 {{ formatFullDate(selected.created_at) }}</span>
              <span v-if="selected.conversation_id"
                >会话 {{ selected.conversation_id.slice(0, 8) }}</span
              >
            </footer>
          </div>

          <section v-else class="jd-criteria" role="tabpanel" aria-label="简历评分标准">
            <div class="jd-criteria__intro">
              <div class="jd-criteria__intro-icon">
                <el-icon :size="22"><DocumentChecked /></el-icon>
              </div>
              <div class="jd-criteria__intro-text">
                <h3>简历评分标准</h3>
                <p>
                  基于「{{ selected.title }}」的职位要求生成，帮助团队用同一把尺子筛选简历；
                  生成后先编辑确认，再保存。
                </p>
              </div>
              <el-button type="primary" :icon="MagicStick" @click="openCriteriaCreate">
                {{ criteriaTotal ? '再生成一份' : 'AI 生成评分标准' }}
              </el-button>
            </div>

            <div v-if="criteriaLoading && !criteriaList.length" class="jd-criteria__loading">
              <el-skeleton :rows="4" animated />
            </div>

            <div v-else-if="!criteriaList.length" class="jd-criteria__empty">
              <div class="jd-criteria__empty-icon">
                <el-icon :size="26"><MagicStick /></el-icon>
              </div>
              <h4>还没有为这个 JD 生成评分标准</h4>
              <p>生成后可随时编辑正文与评分维度，并在简历筛选、AI 简历评价中复用。</p>
              <el-button type="primary" :icon="MagicStick" @click="openCriteriaCreate">
                根据当前 JD 生成
              </el-button>
            </div>

            <div v-else class="jd-criteria__list">
              <article v-for="item in criteriaList" :key="item.id" class="criteria-card">
                <header class="criteria-card__head">
                  <div class="criteria-card__title">
                    <el-tag
                      :type="criteriaStatusOf(item.status).type"
                      size="small"
                      effect="light"
                      round
                    >
                      {{ criteriaStatusOf(item.status).label }}
                    </el-tag>
                    <h4>{{ item.title }}</h4>
                  </div>
                  <time>{{ formatDate(item.updated_at) }}</time>
                </header>
                <p class="criteria-card__preview">
                  {{ item.content_preview || '暂无摘要，打开后可查看完整内容。' }}
                </p>
                <footer class="criteria-card__footer">
                  <div class="criteria-card__meta">
                    <span>{{ item.total_score }} 分制</span>
                    <span>{{ item.dimension_count }} 个评分维度</span>
                  </div>
                  <el-button
                    text
                    type="primary"
                    :loading="criteriaOpeningId === item.id"
                    @click="openCriteriaEdit(item)"
                  >
                    查看 / 编辑
                  </el-button>
                </footer>
              </article>
            </div>
          </section>
        </article>

        <div v-else class="jd-detail-empty">
          <div class="jd-detail-empty__icon">
            <el-icon :size="30"><Document /></el-icon>
          </div>
          <h2>选择一个 JD 查看详情</h2>
          <p>从左侧列表选择已保存的职位描述，或新建一个 JD 并让 AI 帮你起草。</p>
          <el-button type="primary" :icon="Plus" @click="openCreate">新建 JD</el-button>
        </div>
      </main>
    </section>

    <JdEditorDrawer
      v-model="drawerVisible"
      :mode="drawerMode"
      :jd="editingJd"
      @saved="handleSaved"
    />

    <ScoringCriteriaEditorDrawer
      v-model="criteriaDrawerVisible"
      :mode="criteriaDrawerMode"
      :criteria="editingCriteria"
      :preset-jd-id="criteriaPresetJdId"
      lock-jd
      @saved="handleCriteriaSaved"
    />
  </div>
</template>

<style scoped>
.jd-page {
  width: 100%;
  max-width: 1440px;
  margin: 0 auto;
}

.jd-header {
  display: flex;
  gap: 20px;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 20px;
}

.jd-header__eyebrow {
  margin-bottom: 6px;
  font-size: 11px;
  font-weight: 650;
  letter-spacing: 1.4px;
  color: #2563eb;
  text-transform: uppercase;
}

.jd-header h1 {
  font-size: clamp(24px, 2.2vw, 30px);
  font-weight: 700;
  letter-spacing: -0.6px;
  color: #0f172a;
}

.jd-header__desc {
  margin-top: 7px;
  font-size: 13px;
  color: #64748b;
}

.jd-toolbar {
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

.jd-toolbar__search {
  max-width: 360px;
}

.jd-toolbar__status {
  width: 150px;
}

.jd-toolbar__count {
  margin-left: auto;
  font-size: 12px;
  color: #94a3b8;
  white-space: nowrap;
}

.jd-body {
  display: grid;
  grid-template-columns: minmax(300px, 380px) minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}

.jd-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: calc(100vh - 300px);
  padding-right: 4px;
  overflow-y: auto;
}

.jd-list__empty {
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

.jd-list__empty p {
  font-size: 13px;
}

.jd-item {
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

.jd-item:hover {
  border-color: #bfdbfe;
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.07);
  transform: translateY(-1px);
}

.jd-item.is-active {
  background: linear-gradient(180deg, #f8fbff 0%, #ffffff 100%);
  border-color: #2563eb;
  box-shadow: 0 10px 22px rgba(37, 99, 235, 0.12);
}

.jd-item__head {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  justify-content: space-between;
}

.jd-item__head h3 {
  overflow: hidden;
  font-size: 14px;
  font-weight: 650;
  line-height: 1.45;
  color: #0f172a;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.jd-item__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  margin-top: 6px;
  font-size: 11.5px;
  color: #64748b;
}

.jd-item__meta span + span::before {
  margin-right: 6px;
  color: #cbd5e1;
  content: '·';
}

.jd-item__preview {
  display: -webkit-box;
  margin-top: 8px;
  overflow: hidden;
  font-size: 12px;
  line-height: 1.6;
  color: #94a3b8;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.jd-item__footer {
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
  margin-top: 10px;
}

.jd-item__skills {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  min-width: 0;
}

.jd-item__skills span {
  padding: 2px 7px;
  font-size: 10.5px;
  color: #475569;
  background: #f1f5f9;
  border-radius: 999px;
}

.jd-item__skills .jd-item__more {
  color: #2563eb;
  background: #eff6ff;
}

.jd-item__meta .jd-item__criteria {
  font-weight: 550;
  color: #2563eb;
}

.jd-item__footer time {
  flex: none;
  font-size: 10.5px;
  color: #cbd5e1;
}

.jd-list__pagination {
  justify-content: center;
  padding: 6px 0;
}

.jd-detail-shell {
  min-width: 0;
}

.jd-detail-skeleton,
.jd-detail,
.jd-detail-empty {
  padding: 24px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius);
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.02);
}

.jd-detail__header {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  justify-content: space-between;
  padding-bottom: 18px;
  border-bottom: 1px solid #f1f5f9;
}

.jd-detail__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}

.jd-detail__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.jd-detail__actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.jd-detail__header h2 {
  font-size: 22px;
  font-weight: 700;
  letter-spacing: -0.4px;
  color: #0f172a;
}

.jd-detail__updated {
  margin-top: 6px;
  font-size: 11.5px;
  color: #94a3b8;
}

.jd-detail__tabs {
  display: flex;
  gap: 4px;
  width: fit-content;
  padding: 4px;
  margin-top: 16px;
  background: #f1f5f9;
  border-radius: 12px;
}

.jd-tab {
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

.jd-tab:hover {
  color: #2563eb;
}

.jd-tab.is-active {
  color: #1d4ed8;
  background: #ffffff;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.08);
}

.jd-tab .el-icon {
  font-size: 15px;
}

.jd-tab__badge {
  min-width: 18px;
  padding: 0 5px;
  font-size: 10.5px;
  font-weight: 600;
  line-height: 18px;
  color: #1d4ed8;
  text-align: center;
  background: #dbeafe;
  border-radius: 999px;
}

.jd-detail__meta {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  padding: 18px 0;
  margin: 0;
  border-bottom: 1px solid #f1f5f9;
}

.jd-detail__meta dt {
  margin-bottom: 4px;
  font-size: 10.5px;
  color: #94a3b8;
}

.jd-detail__meta dd {
  margin: 0;
  overflow: hidden;
  font-size: 13px;
  font-weight: 550;
  color: #334155;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.jd-detail__section {
  padding-top: 20px;
}

.jd-detail__section h3 {
  margin-bottom: 10px;
  font-size: 14px;
  font-weight: 650;
  color: #0f172a;
}

.jd-detail__skills {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.jd-detail__requirements {
  font-size: 13.5px;
  line-height: 1.8;
  color: #475569;
  white-space: pre-wrap;
}

.jd-detail__footer {
  display: flex;
  gap: 14px;
  justify-content: space-between;
  padding-top: 18px;
  margin-top: 20px;
  font-size: 11px;
  color: #cbd5e1;
  border-top: 1px solid #f1f5f9;
}

.jd-criteria {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding-top: 20px;
}

.jd-criteria__intro {
  display: flex;
  gap: 14px;
  align-items: center;
  padding: 18px;
  background: linear-gradient(135deg, #eff6ff 0%, #f8fbff 100%);
  border: 1px solid #dbeafe;
  border-radius: 14px;
}

.jd-criteria__intro-icon {
  display: grid;
  flex: none;
  place-items: center;
  width: 48px;
  height: 48px;
  color: #2563eb;
  background: #ffffff;
  border-radius: 14px;
  box-shadow: 0 6px 16px rgba(37, 99, 235, 0.12);
}

.jd-criteria__intro-text {
  flex: 1;
  min-width: 0;
}

.jd-criteria__intro-text h3 {
  font-size: 15px;
  font-weight: 650;
  color: #1e3a8a;
}

.jd-criteria__intro-text p {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.7;
  color: #64748b;
}

.jd-criteria__loading {
  padding: 10px 4px;
}

.jd-criteria__empty {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: center;
  padding: 48px 24px;
  text-align: center;
  background: #ffffff;
  border: 1px dashed #cbd5e1;
  border-radius: 14px;
}

.jd-criteria__empty-icon {
  display: grid;
  place-items: center;
  width: 56px;
  height: 56px;
  color: #2563eb;
  background: #eff6ff;
  border-radius: 18px;
}

.jd-criteria__empty h4 {
  font-size: 15px;
  font-weight: 650;
  color: #0f172a;
}

.jd-criteria__empty p {
  max-width: 420px;
  font-size: 12px;
  line-height: 1.7;
  color: #94a3b8;
}

.jd-criteria__list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.criteria-card {
  padding: 16px 18px;
  background: #ffffff;
  border: 1px solid #e5eaf2;
  border-radius: 14px;
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease;
}

.criteria-card:hover {
  border-color: #bfdbfe;
  box-shadow: 0 8px 20px rgba(37, 99, 235, 0.06);
}

.criteria-card__head {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  justify-content: space-between;
}

.criteria-card__title {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  min-width: 0;
}

.criteria-card__title h4 {
  font-size: 14px;
  font-weight: 650;
  line-height: 1.45;
  color: #0f172a;
}

.criteria-card__head time {
  flex: none;
  font-size: 10.5px;
  color: #cbd5e1;
}

.criteria-card__preview {
  display: -webkit-box;
  margin-top: 8px;
  overflow: hidden;
  font-size: 12px;
  line-height: 1.7;
  color: #64748b;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.criteria-card__footer {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  padding-top: 10px;
  margin-top: 10px;
  border-top: 1px dashed #eef2f7;
}

.criteria-card__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.criteria-card__meta span {
  padding: 2px 8px;
  font-size: 10.5px;
  color: #475569;
  background: #f8fafc;
  border-radius: 999px;
}

.jd-detail-empty {
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: center;
  justify-content: center;
  min-height: 440px;
  text-align: center;
}

.jd-detail-empty__icon {
  display: grid;
  place-items: center;
  width: 64px;
  height: 64px;
  color: #2563eb;
  background: #eff6ff;
  border-radius: 20px;
}

.jd-detail-empty h2 {
  font-size: 17px;
  font-weight: 650;
  color: #0f172a;
}

.jd-detail-empty p {
  max-width: 360px;
  margin-bottom: 6px;
  font-size: 12.5px;
  line-height: 1.7;
  color: #94a3b8;
}

@media (max-width: 1080px) {
  .jd-detail__meta {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 860px) {
  .jd-body {
    grid-template-columns: 1fr;
  }

  .jd-list {
    max-height: none;
    padding-right: 0;
  }

  .jd-toolbar {
    flex-wrap: wrap;
  }

  .jd-toolbar__search {
    flex: 1 1 220px;
    max-width: none;
  }

  .jd-toolbar__count {
    width: 100%;
    margin-left: 0;
  }
}

@media (max-width: 760px) {
  .jd-detail__tabs {
    width: 100%;
  }

  .jd-tab {
    flex: 1;
    justify-content: center;
  }

  .jd-criteria__intro {
    flex-direction: column;
    align-items: flex-start;
  }

  .jd-criteria__intro .el-button {
    width: 100%;
  }

  .criteria-card__head,
  .criteria-card__footer {
    flex-direction: column;
    gap: 6px;
  }
}

@media (max-width: 560px) {
  .jd-header {
    flex-direction: column;
  }

  .jd-detail__meta {
    grid-template-columns: 1fr;
  }

  .jd-detail__footer {
    flex-direction: column;
    gap: 4px;
  }
}
</style>
