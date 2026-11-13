<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'

import type { FormInstance, FormRules } from 'element-plus'

import { createKnowledgeBase, updateKnowledgeBase } from '@/api/knowledgeBases'
import type { KnowledgeBase, KnowledgeBasePayload } from '@/api/types'

const props = defineProps<{
  modelValue: boolean
  knowledgeBase?: KnowledgeBase | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: [record: KnowledgeBase]
}>()

interface FormState {
  name: string
  description: string
  category: string
  tags: string[]
  is_public: boolean
  is_searchable: boolean
}

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const isEditing = computed(() => Boolean(props.knowledgeBase?.id))

const formRef = ref<FormInstance>()
const form = reactive<FormState>({
  name: '',
  description: '',
  category: '',
  tags: [],
  is_public: false,
  is_searchable: true,
})
const saving = ref(false)

const rules: FormRules = {
  name: [
    { required: true, message: '请输入知识库名称', trigger: 'blur' },
    { max: 255, message: '名称不能超过 255 个字符', trigger: 'blur' },
  ],
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
  const record = props.knowledgeBase
  form.name = record?.name ?? ''
  form.description = record?.description ?? ''
  form.category = record?.category ?? ''
  form.tags = [...(record?.tags ?? [])]
  form.is_public = record?.is_public ?? false
  form.is_searchable = record?.is_searchable ?? true
  saving.value = false
  void nextTick(() => formRef.value?.clearValidate())
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '保存失败，请稍后重试'
}

function buildPayload(): KnowledgeBasePayload {
  return {
    name: form.name.trim(),
    description: form.description.trim() || null,
    category: form.category.trim() || null,
    tags: form.tags.length ? form.tags : null,
    is_public: form.is_public,
    is_searchable: form.is_searchable,
  }
}

async function handleSubmit(): Promise<void> {
  if (saving.value) return
  try {
    await formRef.value?.validate()
  } catch {
    return
  }

  saving.value = true
  try {
    const record = props.knowledgeBase
    const saved = record
      ? await updateKnowledgeBase(record.id, buildPayload())
      : await createKnowledgeBase(buildPayload())
    ElMessage.success(isEditing.value ? '知识库已更新' : '知识库已创建')
    emit('saved', saved)
    visible.value = false
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="isEditing ? '编辑知识库' : '新建知识库'"
    width="560px"
    :close-on-click-modal="!saving"
    :close-on-press-escape="!saving"
    :show-close="!saving"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
      <el-form-item label="知识库名称" prop="name">
        <el-input
          v-model="form.name"
          maxlength="255"
          show-word-limit
          placeholder="例如：公司制度库"
        />
      </el-form-item>

      <el-form-item label="描述">
        <el-input
          v-model="form.description"
          type="textarea"
          :rows="3"
          maxlength="500"
          show-word-limit
          placeholder="简单说明这个知识库包含哪些内容"
        />
      </el-form-item>

      <el-form-item label="分类">
        <el-input v-model="form.category" maxlength="100" placeholder="例如：制度 / 产品 / 培训" />
      </el-form-item>

      <el-form-item label="标签">
        <el-select
          v-model="form.tags"
          class="kb-form__tags"
          multiple
          filterable
          allow-create
          default-first-option
          placeholder="输入后回车创建标签"
        />
      </el-form-item>

      <div class="kb-form__switches">
        <el-form-item label="公开知识库">
          <el-switch v-model="form.is_public" />
          <span class="kb-form__hint">公开后所有登录用户都能查看</span>
        </el-form-item>
        <el-form-item label="允许搜索">
          <el-switch v-model="form.is_searchable" />
          <span class="kb-form__hint">关闭后该知识库不参与语义检索</span>
        </el-form-item>
      </div>
    </el-form>

    <template #footer>
      <el-button :disabled="saving" @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="handleSubmit">
        {{ saving ? '保存中…' : '保存' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.kb-form__tags {
  width: 100%;
}

.kb-form__switches {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 20px;
}

.kb-form__hint {
  display: block;
  margin-top: 4px;
  font-size: 11.5px;
  line-height: 1.5;
  color: #94a3b8;
}

@media (max-width: 560px) {
  .kb-form__switches {
    grid-template-columns: 1fr;
  }
}
</style>
