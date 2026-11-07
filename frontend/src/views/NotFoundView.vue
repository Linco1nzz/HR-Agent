<script setup lang="ts">
import { computed } from 'vue'

import { ArrowLeft, House } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

const homeTarget = computed(() =>
  auth.isAuthenticated ? { name: 'dashboard' } : { name: 'login' },
)
const homeLabel = computed(() => (auth.isAuthenticated ? '返回工作台' : '前往登录'))
</script>

<template>
  <div class="not-found">
    <el-result icon="warning" title="404" sub-title="抱歉，你访问的页面不存在或已被移除。">
      <template #extra>
        <el-button type="primary" :icon="House" @click="router.replace(homeTarget)">
          {{ homeLabel }}
        </el-button>
        <el-button :icon="ArrowLeft" @click="router.back()">返回上一页</el-button>
      </template>
    </el-result>
  </div>
</template>

<style scoped>
.not-found {
  display: grid;
  place-items: center;
  min-height: 100vh;
  padding: 24px;
  background:
    radial-gradient(circle at 50% 20%, rgba(37, 99, 235, 0.08), transparent 36%), var(--app-bg);
}

.not-found :deep(.el-result__title p) {
  font-size: 46px;
  font-weight: 800;
  letter-spacing: -2px;
  color: #0f172a;
}
</style>
