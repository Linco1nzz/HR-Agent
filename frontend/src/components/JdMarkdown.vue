<script setup lang="ts">
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed } from 'vue'

const props = defineProps<{
  content: string
}>()

const rendered = computed(() => {
  if (!props.content) return ''
  const html = marked.parse(props.content, {
    async: false,
    breaks: true,
    gfm: true,
  }) as string
  return DOMPurify.sanitize(html)
})
</script>

<template>
  <!-- eslint-disable-next-line vue/no-v-html -- rendered 已经过 DOMPurify 清洗 -->
  <div class="jd-markdown" v-html="rendered" />
</template>

<style scoped>
.jd-markdown {
  font-size: 14px;
  line-height: 1.85;
  color: #334155;
  word-break: break-word;
}

.jd-markdown :deep(h1) {
  margin: 22px 0 10px;
  font-size: 21px;
  font-weight: 700;
  line-height: 1.4;
  color: #0f172a;
}

.jd-markdown :deep(h1:first-child) {
  margin-top: 0;
}

.jd-markdown :deep(h2) {
  margin: 20px 0 8px;
  font-size: 17px;
  font-weight: 650;
  color: #0f172a;
}

.jd-markdown :deep(h3) {
  margin: 16px 0 6px;
  font-size: 15px;
  font-weight: 650;
  color: #1e293b;
}

.jd-markdown :deep(p) {
  margin: 8px 0;
}

.jd-markdown :deep(ul),
.jd-markdown :deep(ol) {
  padding-left: 22px;
  margin: 8px 0;
}

.jd-markdown :deep(li) {
  margin: 4px 0;
}

.jd-markdown :deep(strong) {
  font-weight: 650;
  color: #0f172a;
}

.jd-markdown :deep(blockquote) {
  padding: 8px 14px;
  margin: 12px 0;
  color: #475569;
  background: #f8fafc;
  border-left: 3px solid #93b4f5;
  border-radius: 0 8px 8px 0;
}

.jd-markdown :deep(code) {
  padding: 2px 5px;
  font-family: 'JetBrains Mono', Consolas, monospace;
  font-size: 12.5px;
  color: #1d4ed8;
  background: #eff6ff;
  border-radius: 5px;
}

.jd-markdown :deep(pre) {
  padding: 14px 16px;
  overflow-x: auto;
  background: #0f172a;
  border-radius: 10px;
}

.jd-markdown :deep(pre code) {
  padding: 0;
  color: #e2e8f0;
  background: transparent;
}

.jd-markdown :deep(table) {
  width: 100%;
  margin: 12px 0;
  border-collapse: collapse;
}

.jd-markdown :deep(th),
.jd-markdown :deep(td) {
  padding: 8px 10px;
  text-align: left;
  border: 1px solid #e5eaf2;
}

.jd-markdown :deep(th) {
  font-weight: 600;
  color: #1e293b;
  background: #f8fafc;
}

.jd-markdown :deep(hr) {
  margin: 18px 0;
  border: none;
  border-top: 1px solid #e5eaf2;
}

.jd-markdown :deep(a) {
  color: #2563eb;
  text-decoration: underline;
  text-underline-offset: 2px;
}
</style>
