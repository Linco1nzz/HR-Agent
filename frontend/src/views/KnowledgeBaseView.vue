<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  Collection,
  Delete,
  Document,
  Edit,
  Plus,
  Refresh,
  Search,
  Upload,
  View,
} from '@element-plus/icons-vue'

import { deleteDocument, listDocuments, reprocessDocument } from '@/api/documents'
import { deleteKnowledgeBase, listKnowledgeBases } from '@/api/knowledgeBases'
import type {
  DocumentProcessingStatus,
  KnowledgeBase,
  KnowledgeDocumentListItem,
} from '@/api/types'
import DocumentPreviewDialog from '@/components/DocumentPreviewDialog.vue'
import DocumentUploadDialog from '@/components/DocumentUploadDialog.vue'
import KnowledgeBaseEditorDialog from '@/components/KnowledgeBaseEditorDialog.vue'
import { useAuthStore } from '@/stores/auth'

type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'

const statusMeta: Record<DocumentProcessingStatus, { label: string; type: TagType }> = {
  uploaded: { label: '待处理', type: 'info' },
  processing: { label: '处理中', type: 'warning' },
  processed: { label: '已入库', type: 'success' },
  failed: { label: '处理失败', type: 'danger' },
}

const statusOptions = Object.entries(statusMeta).map(([value, meta]) => ({
  value: value as DocumentProcessingStatus,
  label: meta.label,
}))

const auth = useAuthStore()

const kbs = ref<KnowledgeBase[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
const keyword = ref('')
const loading = ref(false)

const showUnassigned = ref(false)
const selectedKbId = ref<string | null>(null)
const orphanTotal = ref(0)

const documents = ref<KnowledgeDocumentListItem[]>([])
const documentTotal = ref(0)
const documentPage = ref(1)
const documentPageSize = ref(10)
const documentKeyword = ref('')
const documentStatus = ref<DocumentProcessingStatus | ''>('')
const documentsLoading = ref(false)

const editorVisible = ref(false)
const editingKb = ref<KnowledgeBase | null>(null)
const uploadVisible = ref(false)
const previewVisible = ref(false)
const previewDocument = ref<KnowledgeDocumentListItem | null>(null)
const actionId = ref<string | null>(null)

const selectedKb = computed(() => kbs.value.find((item) => item.id === selectedKbId.value) ?? null)
const canManage = computed(
  () =>
    Boolean(auth.user?.is_superuser) ||
    Boolean(auth.user?.roles?.includes('超级管理员')) ||
    Boolean(auth.user?.roles?.includes('admin')),
)

const dateFormatter = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

function formatDate(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : dateFormatter.format(date)
}

function formatFileSize(bytes: number): string {
  if (!bytes) return '—'
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}

function statusOf(status: DocumentProcessingStatus): { label: string; type: TagType } {
  return statusMeta[status] ?? statusMeta.uploaded
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '操作失败，请稍后重试'
}

function resetDocumentFilters(): void {
  documentKeyword.value = ''
  documentStatus.value = ''
  documentPage.value = 1
}

async function fetchKnowledgeBases(): Promise<void> {
  loading.value = true
  try {
    const result = await listKnowledgeBases({
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value.trim(),
    })
    kbs.value = result.items
    total.value = result.total

    if (showUnassigned.value) {
      await fetchDocuments()
      return
    }

    const preferred =
      result.items.find((item) => item.id === selectedKbId.value) ?? result.items[0] ?? null
    if (preferred) {
      selectedKbId.value = preferred.id
      await fetchDocuments()
    } else {
      selectedKbId.value = null
      documents.value = []
      documentTotal.value = 0
    }
  } catch (error) {
    kbs.value = []
    total.value = 0
    documents.value = []
    documentTotal.value = 0
    ElMessage.error(errorMessage(error))
  } finally {
    loading.value = false
  }
}

async function fetchOrphanTotal(): Promise<void> {
  try {
    const result = await listDocuments({ unassigned: true, page: 1, page_size: 1 })
    orphanTotal.value = result.total
  } catch {
    orphanTotal.value = 0
  }
}

async function fetchDocuments(): Promise<void> {
  if (!showUnassigned.value && !selectedKbId.value) {
    documents.value = []
    documentTotal.value = 0
    return
  }

  documentsLoading.value = true
  try {
    const result = await listDocuments({
      page: documentPage.value,
      page_size: documentPageSize.value,
      keyword: documentKeyword.value.trim(),
      processing_status: documentStatus.value,
      ...(showUnassigned.value
        ? { unassigned: true }
        : { knowledge_base_id: selectedKbId.value ?? undefined }),
    })
    documents.value = result.items
    documentTotal.value = result.total
  } catch (error) {
    documents.value = []
    documentTotal.value = 0
    ElMessage.error(errorMessage(error))
  } finally {
    documentsLoading.value = false
  }
}

function selectKnowledgeBase(record: KnowledgeBase): void {
  if (!showUnassigned.value && selectedKbId.value === record.id) return
  showUnassigned.value = false
  selectedKbId.value = record.id
  resetDocumentFilters()
  void fetchDocuments()
}

function selectUnassigned(): void {
  if (showUnassigned.value) return
  showUnassigned.value = true
  selectedKbId.value = null
  resetDocumentFilters()
  void fetchDocuments()
}

function handleSearch(): void {
  page.value = 1
  void fetchKnowledgeBases()
}

function handlePageChange(nextPage: number): void {
  page.value = nextPage
  void fetchKnowledgeBases()
}

function handleDocumentSearch(): void {
  documentPage.value = 1
  void fetchDocuments()
}

function handleDocumentPageChange(nextPage: number): void {
  documentPage.value = nextPage
  void fetchDocuments()
}

function openCreate(): void {
  editingKb.value = null
  editorVisible.value = true
}

function openEdit(): void {
  if (!selectedKb.value) return
  editingKb.value = selectedKb.value
  editorVisible.value = true
}

async function handleKbSaved(record: KnowledgeBase): Promise<void> {
  showUnassigned.value = false
  selectedKbId.value = record.id
  keyword.value = ''
  page.value = 1
  await fetchKnowledgeBases()
}

async function confirmAction(message: string, title: string): Promise<boolean> {
  try {
    await ElMessageBox.confirm(message, title, {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
    return true
  } catch {
    return false
  }
}

async function handleDeleteKb(): Promise<void> {
  const record = selectedKb.value
  if (!record) return

  const confirmed = await confirmAction(
    `删除「${record.name}」后，其下 ${record.document_count} 份文档会转为未关联状态。` +
      '文档文件与向量分块都会保留，只有删除文档时才会清理。',
    '删除知识库？',
  )
  if (!confirmed) return

  try {
    await deleteKnowledgeBase(record.id)
    ElMessage.success('知识库已删除，关联文档已转为未关联')
    selectedKbId.value = null
    await fetchKnowledgeBases()
    await fetchOrphanTotal()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

function openUpload(): void {
  if (!selectedKb.value) return
  uploadVisible.value = true
}

async function handleUploaded(): Promise<void> {
  uploadVisible.value = false
  if (selectedKb.value) {
    selectedKb.value.document_count += 1
  }
  documentPage.value = 1
  await fetchDocuments()
}

function openPreview(record: KnowledgeDocumentListItem): void {
  previewDocument.value = record
  previewVisible.value = true
}

async function handleDeleteDocument(record: KnowledgeDocumentListItem): Promise<void> {
  const confirmed = await confirmAction(
    `删除「${record.original_filename}」会同时清理文件与 ${record.chunk_count} 个向量分块，且无法恢复。`,
    '删除文档？',
  )
  if (!confirmed) return

  actionId.value = record.id
  try {
    await deleteDocument(record.id)
    ElMessage.success('文档已删除')
    if (showUnassigned.value) {
      await fetchOrphanTotal()
    } else if (selectedKb.value) {
      selectedKb.value.document_count = Math.max(0, selectedKb.value.document_count - 1)
    }
    if (documents.value.length === 1 && documentPage.value > 1) {
      documentPage.value -= 1
    }
    await fetchDocuments()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    actionId.value = null
  }
}

async function handleReprocess(record: KnowledgeDocumentListItem): Promise<void> {
  actionId.value = record.id
  try {
    const updated = await reprocessDocument(record.id)
    if (updated.processing_status === 'processed') {
      ElMessage.success(`处理完成，共 ${updated.chunk_count} 个分块`)
    } else {
      ElMessage.warning(`处理失败：${updated.processing_error ?? '未知原因'}`)
    }
    await fetchDocuments()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    actionId.value = null
  }
}

onMounted(() => {
  void fetchKnowledgeBases()
  void fetchOrphanTotal()
})
</script>

<template>
  <div class="kb-page">
    <section class="kb-header">
      <div>
        <p class="kb-header__eyebrow">知识中心</p>
        <h1>知识库</h1>
        <p class="kb-header__desc">
          按主题管理文档，上传后自动解析、切块并向量化，供 AI 检索使用。
        </p>
      </div>
      <el-button type="primary" :icon="Plus" size="large" @click="openCreate">
        新建知识库
      </el-button>
    </section>

    <section class="kb-toolbar">
      <el-input
        v-model="keyword"
        class="kb-toolbar__search"
        clearable
        :prefix-icon="Search"
        placeholder="搜索知识库名称或描述"
        @keyup.enter="handleSearch"
        @clear="handleSearch"
      />
      <el-button :icon="Refresh" :loading="loading" @click="handleSearch">刷新</el-button>
      <span class="kb-toolbar__count">共 {{ total }} 个知识库</span>
    </section>

    <section class="kb-body">
      <aside class="kb-list" aria-label="知识库列表">
        <el-skeleton v-if="loading && !kbs.length" :rows="5" animated />

        <template v-else>
          <button
            type="button"
            class="kb-item kb-item--orphan"
            :class="{ 'is-active': showUnassigned }"
            @click="selectUnassigned"
          >
            <div class="kb-item__head">
              <h3>未关联文档</h3>
              <el-tag size="small" type="info" effect="plain" round>{{ orphanTotal }}</el-tag>
            </div>
            <p class="kb-item__desc">知识库删除后保留的文档，可继续预览或删除</p>
          </button>

          <div v-if="!kbs.length" class="kb-list__empty">
            <el-icon :size="30"><Collection /></el-icon>
            <p>{{ keyword ? '没有匹配的知识库' : '还没有知识库' }}</p>
            <el-button v-if="!keyword" type="primary" text @click="openCreate">
              新建第一个知识库
            </el-button>
          </div>

          <button
            v-for="kb in kbs"
            :key="kb.id"
            type="button"
            class="kb-item"
            :class="{ 'is-active': !showUnassigned && kb.id === selectedKbId }"
            @click="selectKnowledgeBase(kb)"
          >
            <div class="kb-item__head">
              <h3>{{ kb.name }}</h3>
              <el-tag size="small" :type="kb.is_public ? 'success' : 'info'" effect="plain" round>
                {{ kb.is_public ? '公开' : '私有' }}
              </el-tag>
            </div>
            <p class="kb-item__desc">{{ kb.description || '暂无描述' }}</p>
            <div class="kb-item__meta">
              <span>{{ kb.category || '未分类' }}</span>
              <span>{{ kb.document_count }} 篇文档</span>
            </div>
          </button>
        </template>

        <el-pagination
          v-if="total > pageSize"
          class="kb-list__pagination"
          small
          background
          layout="prev, pager, next"
          :current-page="page"
          :page-size="pageSize"
          :total="total"
          @current-change="handlePageChange"
        />
      </aside>

      <main class="kb-detail">
        <header v-if="showUnassigned" class="kb-detail__header">
          <div>
            <h2>未关联文档</h2>
            <p>知识库已被删除，但文档文件与向量分块仍然保留。删除文档时会一并清理。</p>
          </div>
        </header>

        <header v-else-if="selectedKb" class="kb-detail__header">
          <div class="kb-detail__title">
            <div>
              <div class="kb-detail__tags">
                <el-tag :type="selectedKb.is_public ? 'success' : 'info'" effect="light" round>
                  {{ selectedKb.is_public ? '公开' : '私有' }}
                </el-tag>
                <el-tag v-if="!selectedKb.is_searchable" type="warning" effect="plain" round>
                  不可搜索
                </el-tag>
                <el-tag v-if="selectedKb.category" type="info" effect="plain" round>
                  {{ selectedKb.category }}
                </el-tag>
              </div>
              <h2>{{ selectedKb.name }}</h2>
              <p>{{ selectedKb.description || '暂无描述' }}</p>
              <div class="kb-detail__meta">
                <span>{{ selectedKb.document_count }} 篇文档</span>
                <span>创建于 {{ formatDate(selectedKb.created_at) }}</span>
                <span v-if="selectedKb.tags?.length">标签：{{ selectedKb.tags.join('、') }}</span>
              </div>
            </div>
          </div>

          <div v-if="canManage" class="kb-detail__actions">
            <el-button :icon="Edit" @click="openEdit">编辑</el-button>
            <el-button type="danger" plain :icon="Delete" @click="handleDeleteKb">删除</el-button>
          </div>
        </header>

        <header v-else class="kb-detail__header">
          <div>
            <h2>选择一个知识库</h2>
            <p>从左侧选择知识库查看其文档，或新建一个知识库开始上传资料。</p>
          </div>
        </header>

        <section v-if="showUnassigned || selectedKb" class="doc-toolbar">
          <el-input
            v-model="documentKeyword"
            class="doc-toolbar__search"
            clearable
            :prefix-icon="Search"
            placeholder="搜索文件名或正文"
            @keyup.enter="handleDocumentSearch"
            @clear="handleDocumentSearch"
          />
          <el-select
            v-model="documentStatus"
            class="doc-toolbar__status"
            clearable
            placeholder="全部状态"
            @change="handleDocumentSearch"
          >
            <el-option
              v-for="option in statusOptions"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
          <el-button :icon="Refresh" :loading="documentsLoading" @click="handleDocumentSearch">
            刷新
          </el-button>
          <el-button v-if="!showUnassigned" type="primary" :icon="Upload" @click="openUpload">
            上传文档
          </el-button>
          <span class="doc-toolbar__count">共 {{ documentTotal }} 份文档</span>
        </section>

        <section v-if="showUnassigned || selectedKb" class="doc-list">
          <el-skeleton v-if="documentsLoading && !documents.length" :rows="4" animated />

          <div v-else-if="!documents.length" class="doc-list__empty">
            <el-icon :size="30"><Document /></el-icon>
            <p>
              {{
                documentKeyword || documentStatus
                  ? '没有匹配的文档'
                  : showUnassigned
                    ? '暂无未关联文档'
                    : '这个知识库还没有文档'
              }}
            </p>
            <el-button
              v-if="!showUnassigned && !documentKeyword && !documentStatus"
              type="primary"
              text
              @click="openUpload"
            >
              上传第一份文档
            </el-button>
          </div>

          <article v-for="doc in documents" :key="doc.id" class="doc-item">
            <div class="doc-item__icon">
              <el-icon :size="20"><Document /></el-icon>
            </div>

            <div class="doc-item__body">
              <div class="doc-item__title">
                <h3>{{ doc.original_filename }}</h3>
                <el-tag
                  :type="statusOf(doc.processing_status).type"
                  size="small"
                  effect="light"
                  round
                >
                  {{ statusOf(doc.processing_status).label }}
                </el-tag>
              </div>
              <p class="doc-item__meta">
                <span>{{ formatFileSize(doc.file_size) }}</span>
                <span>{{ doc.chunk_count }} 个分块</span>
                <span v-if="showUnassigned">{{ doc.knowledge_base_name || '未关联' }}</span>
                <span>{{ formatDate(doc.created_at) }}</span>
              </p>
              <p
                v-if="doc.processing_status === 'failed' && doc.processing_error"
                class="doc-item__error"
              >
                {{ doc.processing_error }}
              </p>
            </div>

            <div class="doc-item__actions">
              <el-button size="small" :icon="View" @click="openPreview(doc)">预览</el-button>
              <el-button
                v-if="doc.processing_status === 'failed'"
                size="small"
                :icon="Refresh"
                :loading="actionId === doc.id"
                @click="handleReprocess(doc)"
              >
                重新处理
              </el-button>
              <el-button
                size="small"
                type="danger"
                plain
                :icon="Delete"
                :loading="actionId === doc.id"
                @click="handleDeleteDocument(doc)"
              >
                删除
              </el-button>
            </div>
          </article>

          <el-pagination
            v-if="documentTotal > documentPageSize"
            class="doc-list__pagination"
            small
            background
            layout="prev, pager, next"
            :current-page="documentPage"
            :page-size="documentPageSize"
            :total="documentTotal"
            @current-change="handleDocumentPageChange"
          />
        </section>

        <div v-else class="kb-detail__empty">
          <div class="kb-detail__empty-icon">
            <el-icon :size="30"><Collection /></el-icon>
          </div>
          <h2>选择左侧知识库</h2>
          <p>选中知识库后，这里会显示它的文档、处理状态与分块预览。</p>
        </div>
      </main>
    </section>

    <KnowledgeBaseEditorDialog
      v-model="editorVisible"
      :knowledge-base="editingKb"
      @saved="handleKbSaved"
    />

    <DocumentUploadDialog
      v-if="selectedKb"
      v-model="uploadVisible"
      :knowledge-base-id="selectedKb.id"
      :knowledge-base-name="selectedKb.name"
      @uploaded="handleUploaded"
    />

    <DocumentPreviewDialog v-model="previewVisible" :document="previewDocument" />
  </div>
</template>

<style scoped>
.kb-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.kb-header {
  display: flex;
  gap: 20px;
  align-items: flex-end;
  justify-content: space-between;
}

.kb-header__eyebrow {
  margin-bottom: 6px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1.6px;
  color: #94a3b8;
  text-transform: uppercase;
}

.kb-header h1 {
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.5px;
  color: #0f172a;
}

.kb-header__desc {
  margin-top: 6px;
  font-size: 13px;
  color: #64748b;
}

.kb-toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 12px 16px;
  background: #ffffff;
  border: 1px solid var(--app-border);
  border-radius: 14px;
  box-shadow: var(--app-shadow);
}

.kb-toolbar__search {
  max-width: 320px;
}

.kb-toolbar__count {
  margin-left: auto;
  font-size: 12px;
  color: #94a3b8;
}

.kb-body {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}

.kb-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  background: #ffffff;
  border: 1px solid var(--app-border);
  border-radius: 16px;
  box-shadow: var(--app-shadow);
}

.kb-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px;
  text-align: left;
  cursor: pointer;
  background: #ffffff;
  border: 1px solid transparent;
  border-radius: 12px;
  transition:
    background 0.16s ease,
    border-color 0.16s ease;
}

.kb-item:hover {
  background: #f8fafc;
  border-color: #e2e8f0;
}

.kb-item.is-active {
  background: #eff6ff;
  border-color: #bfdbfe;
}

.kb-item__head {
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
}

.kb-item__head h3 {
  overflow: hidden;
  font-size: 13.5px;
  font-weight: 650;
  color: #1e293b;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kb-item__desc {
  display: -webkit-box;
  overflow: hidden;
  font-size: 12px;
  line-height: 1.6;
  color: #64748b;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.kb-item__meta {
  display: flex;
  gap: 10px;
  font-size: 11px;
  color: #94a3b8;
}

.kb-item--orphan {
  border-style: dashed;
  border-color: #e2e8f0;
}

.kb-list__empty {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: center;
  padding: 34px 12px;
  font-size: 12px;
  color: #94a3b8;
}

.kb-list__pagination {
  justify-content: center;
  padding-top: 4px;
}

.kb-detail {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.kb-detail__header {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  justify-content: space-between;
  padding: 20px 22px;
  background: #ffffff;
  border: 1px solid var(--app-border);
  border-radius: 16px;
  box-shadow: var(--app-shadow);
}

.kb-detail__title {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}

.kb-detail__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}

.kb-detail__header h2 {
  font-size: 19px;
  font-weight: 700;
  color: #0f172a;
}

.kb-detail__header p {
  max-width: 720px;
  margin-top: 6px;
  font-size: 12.5px;
  line-height: 1.7;
  color: #64748b;
}

.kb-detail__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-top: 10px;
  font-size: 11.5px;
  color: #94a3b8;
}

.kb-detail__actions {
  display: flex;
  flex: none;
  gap: 8px;
}

.doc-toolbar {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 12px 16px;
  background: #ffffff;
  border: 1px solid var(--app-border);
  border-radius: 14px;
}

.doc-toolbar__search {
  max-width: 280px;
}

.doc-toolbar__status {
  width: 130px;
}

.doc-toolbar__count {
  margin-left: auto;
  font-size: 12px;
  color: #94a3b8;
}

.doc-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.doc-item {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  padding: 16px 18px;
  background: #ffffff;
  border: 1px solid var(--app-border);
  border-radius: 14px;
  transition: border-color 0.16s ease;
}

.doc-item:hover {
  border-color: #c7d7ee;
}

.doc-item__icon {
  display: grid;
  flex: none;
  place-items: center;
  width: 40px;
  height: 40px;
  color: #2563eb;
  background: #eff6ff;
  border-radius: 11px;
}

.doc-item__body {
  flex: 1;
  min-width: 0;
}

.doc-item__title {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.doc-item__title h3 {
  overflow: hidden;
  font-size: 13.5px;
  font-weight: 650;
  color: #1e293b;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-item__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 6px;
  font-size: 11.5px;
  color: #94a3b8;
}

.doc-item__error {
  margin-top: 8px;
  font-size: 11.5px;
  line-height: 1.6;
  color: #b91c1c;
}

.doc-item__actions {
  display: flex;
  flex: none;
  gap: 6px;
  align-items: center;
}

.doc-list__empty {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: center;
  padding: 48px 16px;
  font-size: 12.5px;
  color: #94a3b8;
  background: #ffffff;
  border: 1px dashed #dbe3ef;
  border-radius: 16px;
}

.doc-list__pagination {
  justify-content: center;
  padding-top: 4px;
}

.kb-detail__empty {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: center;
  padding: 72px 20px;
  text-align: center;
  background: #ffffff;
  border: 1px dashed #dbe3ef;
  border-radius: 16px;
}

.kb-detail__empty-icon {
  display: grid;
  place-items: center;
  width: 58px;
  height: 58px;
  color: #2563eb;
  background: #eff6ff;
  border-radius: 16px;
}

.kb-detail__empty h2 {
  margin-top: 6px;
  font-size: 16px;
  color: #1e293b;
}

.kb-detail__empty p {
  max-width: 420px;
  font-size: 12.5px;
  line-height: 1.7;
  color: #94a3b8;
}

@media (max-width: 1100px) {
  .kb-body {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .kb-header,
  .kb-toolbar,
  .doc-toolbar {
    flex-wrap: wrap;
    align-items: stretch;
  }

  .kb-toolbar__search,
  .doc-toolbar__search,
  .doc-toolbar__status {
    max-width: none;
    width: 100%;
  }

  .kb-toolbar__count,
  .doc-toolbar__count {
    margin-left: 0;
  }

  .kb-detail__header {
    flex-direction: column;
  }

  .doc-item {
    flex-wrap: wrap;
  }

  .doc-item__actions {
    width: 100%;
    justify-content: flex-end;
  }
}
</style>
