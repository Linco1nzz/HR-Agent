<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { ArrowDown, Expand, Fold, House, SwitchButton } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const collapsed = ref(false)
const mobileOpen = ref(false)
const isMobile = ref(false)

const displayName = computed(
  () => auth.user?.full_name?.trim() || auth.user?.username || '未登录用户',
)
const userInitial = computed(() => displayName.value.slice(0, 1).toUpperCase())
const roleLabel = computed(() => {
  if (auth.user?.roles.length) {
    return auth.user.roles[0]
  }
  return auth.user?.is_superuser ? '超级管理员' : '成员'
})
const pageTitle = computed(() => route.meta.title ?? '工作台')
const sidebarClosed = computed(() => (isMobile.value ? !mobileOpen.value : collapsed.value))

const today = new Intl.DateTimeFormat('zh-CN', {
  month: 'long',
  day: 'numeric',
  weekday: 'long',
}).format(new Date())

let mediaQuery: MediaQueryList | null = null

function handleMediaChange(event: MediaQueryListEvent): void {
  isMobile.value = event.matches
  if (!event.matches) {
    mobileOpen.value = false
  }
}

function toggleSidebar(): void {
  if (isMobile.value) {
    mobileOpen.value = !mobileOpen.value
  } else {
    collapsed.value = !collapsed.value
  }
}

async function handleLogout(): Promise<void> {
  try {
    await ElMessageBox.confirm('退出后需要重新登录才能继续使用工作台。', '确认退出登录？', {
      confirmButtonText: '退出登录',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }

  await auth.logout()
  ElMessage.success('已退出登录')
  await router.replace({ name: 'login' })
}

function handleCommand(command: string | number | object): void {
  if (command === 'logout') {
    void handleLogout()
  }
}

watch(
  () => route.fullPath,
  () => {
    mobileOpen.value = false
  },
)

onMounted(() => {
  mediaQuery = window.matchMedia('(max-width: 900px)')
  isMobile.value = mediaQuery.matches
  mediaQuery.addEventListener('change', handleMediaChange)
})

onBeforeUnmount(() => {
  mediaQuery?.removeEventListener('change', handleMediaChange)
})
</script>

<template>
  <div
    class="app-shell"
    :class="{ 'is-collapsed': collapsed, 'is-mobile-open': mobileOpen, 'is-mobile': isMobile }"
  >
    <div class="app-shell__backdrop" @click="mobileOpen = false" />

    <aside class="sidebar">
      <div class="sidebar__brand">
        <div class="brand-mark">HR</div>
        <div v-if="!sidebarClosed || isMobile" class="sidebar__brand-text">
          <strong>HR-Agent</strong>
          <span>AI 人力资源助手</span>
        </div>
      </div>

      <nav class="sidebar__nav" aria-label="主导航">
        <p v-if="!sidebarClosed || isMobile" class="sidebar__section">工作空间</p>
        <el-menu
          :default-active="route.path"
          :collapse="sidebarClosed && !isMobile"
          :collapse-transition="false"
          router
          class="sidebar__menu"
        >
          <el-menu-item index="/dashboard">
            <el-icon><House /></el-icon>
            <template #title>工作台</template>
          </el-menu-item>
        </el-menu>
      </nav>

      <div class="sidebar__footer">
        <div v-if="!sidebarClosed || isMobile" class="sidebar__footer-card">
          <span class="sidebar__status-dot" />
          <div>
            <strong>开发环境</strong>
            <small>v0.1.0 · 前端已就绪</small>
          </div>
        </div>
        <div v-else class="sidebar__status-dot sidebar__status-dot--solo" />
      </div>
    </aside>

    <div class="app-shell__main">
      <header class="topbar">
        <div class="topbar__left">
          <el-button
            text
            circle
            class="topbar__toggle"
            :aria-label="sidebarClosed ? '展开导航' : '收起导航'"
            @click="toggleSidebar"
          >
            <el-icon :size="19">
              <Expand v-if="sidebarClosed" />
              <Fold v-else />
            </el-icon>
          </el-button>

          <el-breadcrumb separator="/" class="topbar__breadcrumb">
            <el-breadcrumb-item :to="{ name: 'dashboard' }">HR-Agent</el-breadcrumb-item>
            <el-breadcrumb-item>{{ pageTitle }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>

        <div class="topbar__right">
          <span class="topbar__date">{{ today }}</span>

          <el-dropdown trigger="click" @command="handleCommand">
            <button class="user-trigger" type="button" aria-label="账号菜单">
              <el-avatar :size="36" :src="auth.user?.avatar_url || undefined">
                {{ userInitial }}
              </el-avatar>
              <span class="user-trigger__meta">
                <strong>{{ displayName }}</strong>
                <small>{{ roleLabel }}</small>
              </span>
              <el-icon class="user-trigger__arrow"><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">
                  <el-icon><SwitchButton /></el-icon>
                  退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <main class="app-content">
        <router-view v-slot="{ Component }">
          <transition name="page" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  width: 100%;
  height: 100vh;
  overflow: hidden;
}

.sidebar {
  position: relative;
  z-index: 30;
  display: flex;
  flex: none;
  flex-direction: column;
  width: 240px;
  padding: 0 14px;
  overflow: hidden;
  color: #ffffff;
  background:
    radial-gradient(circle at 30% 0%, rgba(37, 99, 235, 0.28), transparent 38%), var(--app-sidebar);
  border-right: 1px solid rgba(255, 255, 255, 0.04);
  transition: width 0.22s ease;
}

.is-collapsed .sidebar {
  width: 76px;
}

.sidebar__brand {
  display: flex;
  gap: 12px;
  align-items: center;
  height: 76px;
  padding: 0 6px;
}

.sidebar__brand .brand-mark {
  width: 38px;
  height: 38px;
  font-size: 14px;
  border-radius: 11px;
  box-shadow: 0 8px 20px rgba(2, 8, 23, 0.35);
}

.sidebar__brand-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
  line-height: 1.3;
  white-space: nowrap;
}

.sidebar__brand-text strong {
  font-size: 15px;
  letter-spacing: 0.2px;
}

.sidebar__brand-text span {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.42);
}

.sidebar__nav {
  padding-top: 18px;
}

.sidebar__section {
  padding: 0 12px;
  margin-bottom: 8px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 1.6px;
  color: rgba(255, 255, 255, 0.3);
  white-space: nowrap;
}

.sidebar__menu {
  background: transparent;
  border-right: none;
}

.sidebar__menu :deep(.el-menu-item) {
  height: 46px;
  margin-bottom: 6px;
  line-height: 46px;
  color: rgba(255, 255, 255, 0.62);
  border-radius: 10px;
}

.sidebar__menu :deep(.el-menu-item .el-icon) {
  font-size: 18px;
}

.sidebar__menu :deep(.el-menu-item:hover) {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.07);
}

.sidebar__menu :deep(.el-menu-item.is-active) {
  font-weight: 600;
  color: #ffffff;
  background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
  box-shadow: 0 8px 20px rgba(37, 99, 235, 0.28);
}

.sidebar__menu :deep(.el-menu-item.is-active::after) {
  display: none;
}

.sidebar__footer {
  padding: 16px 0 20px;
  margin-top: auto;
}

.sidebar__footer-card {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 12px;
  background: rgba(255, 255, 255, 0.045);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 12px;
}

.sidebar__footer-card div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  white-space: nowrap;
}

.sidebar__footer-card strong {
  font-size: 12px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.82);
}

.sidebar__footer-card small {
  font-size: 10px;
  color: rgba(255, 255, 255, 0.34);
}

.sidebar__status-dot {
  flex: none;
  width: 8px;
  height: 8px;
  background: #34d399;
  border-radius: 50%;
  box-shadow: 0 0 0 3px rgba(52, 211, 153, 0.16);
}

.sidebar__status-dot--solo {
  margin: 0 auto;
}

.app-shell__main {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
}

.topbar {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: space-between;
  height: 68px;
  padding: 0 26px 0 16px;
  background: rgba(255, 255, 255, 0.82);
  border-bottom: 1px solid var(--app-border);
  backdrop-filter: blur(14px);
}

.topbar__left,
.topbar__right {
  display: flex;
  gap: 14px;
  align-items: center;
  min-width: 0;
}

.topbar__toggle {
  color: #64748b;
}

.topbar__toggle:hover {
  color: var(--app-primary);
  background: var(--el-color-primary-light-9);
}

.topbar__breadcrumb :deep(.el-breadcrumb__inner) {
  font-size: 13px;
  color: #94a3b8;
}

.topbar__breadcrumb :deep(.el-breadcrumb__item:last-child .el-breadcrumb__inner) {
  font-weight: 600;
  color: #334155;
}

.topbar__date {
  font-size: 12px;
  color: #94a3b8;
  white-space: nowrap;
}

.user-trigger {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 5px 8px 5px 5px;
  cursor: pointer;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 12px;
  transition:
    background 0.18s ease,
    border-color 0.18s ease;
}

.user-trigger:hover {
  background: #f8fafc;
  border-color: var(--app-border);
}

.user-trigger :deep(.el-avatar) {
  color: #ffffff;
  background: linear-gradient(135deg, #3b82f6, #1d4ed8);
}

.user-trigger__meta {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  text-align: left;
}

.user-trigger__meta strong {
  max-width: 140px;
  overflow: hidden;
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-trigger__meta small {
  font-size: 11px;
  color: #94a3b8;
}

.user-trigger__arrow {
  font-size: 12px;
  color: #94a3b8;
}

.app-content {
  flex: 1;
  padding: 28px;
  overflow-y: auto;
}

.app-shell__backdrop {
  display: none;
}

@media (max-width: 900px) {
  .sidebar {
    position: fixed;
    top: 0;
    bottom: 0;
    left: 0;
    width: 260px !important;
    transform: translateX(-100%);
    transition: transform 0.22s ease;
  }

  .is-mobile-open .sidebar {
    transform: translateX(0);
  }

  .is-mobile-open .app-shell__backdrop {
    position: fixed;
    inset: 0;
    z-index: 20;
    display: block;
    background: rgba(15, 23, 42, 0.42);
    backdrop-filter: blur(2px);
  }

  .topbar {
    padding: 0 16px;
  }

  .topbar__breadcrumb {
    display: none;
  }

  .topbar__date {
    display: none;
  }

  .app-content {
    padding: 18px;
  }
}

@media (max-width: 560px) {
  .user-trigger__meta,
  .user-trigger__arrow {
    display: none;
  }
}
</style>
