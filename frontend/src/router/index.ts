import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import { setUnauthorizedHandler } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

declare module 'vue-router' {
  interface RouteMeta {
    /** 浏览器标题 */
    title?: string
    /** 是否需要登录；默认 false */
    requiresAuth?: boolean
  }
}

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { title: '登录', requiresAuth: false },
  },
  {
    path: '/',
    component: () => import('@/layouts/DefaultLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        redirect: { name: 'dashboard' },
      },
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/DashboardView.vue'),
        meta: { title: '工作台', requiresAuth: true },
      },
      {
        path: 'jds',
        name: 'jds',
        component: () => import('@/views/JdView.vue'),
        meta: { title: 'JD 管理', requiresAuth: true },
      },
      {
        path: 'resumes',
        name: 'resumes',
        component: () => import('@/views/ResumeView.vue'),
        meta: { title: '简历筛选', requiresAuth: true },
      },
      {
        path: 'scoring-criteria',
        // 旧的独立页面入口保留兼容，统一回到 JD 管理页的评分标准标签
        redirect: { name: 'jds' },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFoundView.vue'),
    meta: { title: '页面不存在', requiresAuth: false },
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

const APP_TITLE = 'HR-Agent'

router.beforeEach(async (to) => {
  const auth = useAuthStore()

  if (to.meta.requiresAuth) {
    if (!auth.token) {
      return { name: 'login', query: { redirect: to.fullPath } }
    }

    if (!auth.user) {
      try {
        await auth.fetchCurrentUser()
      } catch {
        auth.reset()
        return { name: 'login', query: { redirect: to.fullPath } }
      }
    }
  } else if (to.name === 'login' && auth.token) {
    return { name: 'dashboard' }
  }

  return true
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · ${APP_TITLE}` : APP_TITLE
})

// 任意接口返回 401 时统一清理会话；具体业务错误由页面自行提示
setUnauthorizedHandler(() => {
  const auth = useAuthStore()
  auth.reset()

  const current = router.currentRoute.value
  if (current.name && current.name !== 'login') {
    void router.replace({ name: 'login', query: { redirect: current.fullPath } })
  }
})

export default router
