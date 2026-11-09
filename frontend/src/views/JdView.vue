<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { Document, Edit, Plus, Refresh, Search } from '@element-plus/icons-vue'

import { getJd, listJds } from '@/api/jds'
import type { JdStatus, JobDescription, JobDescriptionListItem } from '@/api/types'
import JdEditorDrawer from '@/components/JdEditorDrawer.vue'
import JdMarkdown from '@/components/JdMarkdown.vue'

type TagType = 'primary' | 'success' | 'warning' | 'info'

const statusMeta: Record<JdStatus, { label: string; type: TagType }> = {
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

const drawerVisible = ref(false)
const drawerMode = ref<'create' | 'edit'>('create')
const editingJd = ref<JobDescription | null>(null)

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

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '加载失败，请稍后重试'
}

async function loadDetail(id: string, force = false): Promise<void> {
  if (!force && selectedId.value === id && selected.value) return
  selectedId.value = id
  detailLoading.value = true
  try {
    selected.value = await getJd(id)
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
    }
  } catch (error) {
    jds.value = []
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
        <p class="jd-header__desc">集中管理职位描述，支持 AI 生成、在线编辑与状态跟踪。</p>
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
            <el-button type="primary" plain :icon="Edit" @click="openEdit">编辑</el-button>
          </header>

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
