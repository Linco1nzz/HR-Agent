<script setup lang="ts">
import { reactive, ref } from 'vue'

import {
  ArrowRight,
  ChatDotRound,
  DataAnalysis,
  Lock,
  User,
  UserFilled,
} from '@element-plus/icons-vue'
import type { FormInstance, FormRules } from 'element-plus'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'

import { ApiError } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { isLoggingIn } = storeToRefs(auth)

const formRef = ref<FormInstance>()
const form = reactive({
  username: '',
  password: '',
})

const rules: FormRules<typeof form> = {
  username: [{ required: true, message: '请输入用户名或邮箱', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

const features = [
  {
    icon: DataAnalysis,
    title: '组织洞察',
    description: '人员结构、流动与编制一目了然',
  },
  {
    icon: UserFilled,
    title: '员工全周期',
    description: '从入职到成长，档案集中管理',
  },
  {
    icon: ChatDotRound,
    title: 'AI 协作',
    description: '用自然语言快速完成 HR 事务',
  },
]

function resolveRedirect(): string {
  const redirect = route.query.redirect
  if (typeof redirect === 'string' && redirect.startsWith('/') && !redirect.startsWith('//')) {
    return redirect
  }
  return '/dashboard'
}

async function handleSubmit(): Promise<void> {
  if (!formRef.value) {
    return
  }

  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) {
    return
  }

  try {
    await auth.login({ username: form.username.trim(), password: form.password })
    ElMessage.success('登录成功')
    await router.replace(resolveRedirect())
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '登录失败，请稍后重试')
  }
}
</script>

<template>
  <div class="login">
    <section class="login__brand">
      <div class="brand">
        <div class="brand-mark">HR</div>
        <div class="brand__text">
          <strong>HR-Agent</strong>
          <span>AI 人力资源助手</span>
        </div>
      </div>

      <div class="brand__content">
        <p class="brand__eyebrow">PEOPLE · DATA · INTELLIGENCE</p>
        <h1>让每一次人才决策<br />都有数据支撑</h1>
        <p class="brand__description">
          统一员工、组织与招聘数据，用 AI 把 HR
          从重复事务中解放出来，专注于真正重要的组织与人才发展。
        </p>

        <ul class="feature-list">
          <li v-for="feature in features" :key="feature.title" class="feature">
            <span class="feature__icon">
              <el-icon><component :is="feature.icon" /></el-icon>
            </span>
            <span>
              <strong>{{ feature.title }}</strong>
              <small>{{ feature.description }}</small>
            </span>
          </li>
        </ul>
      </div>

      <p class="brand__footer">© {{ new Date().getFullYear() }} HR-Agent · 内部人力资源平台</p>
    </section>

    <section class="login__panel">
      <div class="login-card">
        <div class="login-card__head">
          <div class="brand-mark brand-mark--small">HR</div>
          <h2>欢迎回来</h2>
          <p>登录后进入 HR-Agent 工作台</p>
        </div>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          label-position="top"
          size="large"
          @submit.prevent="handleSubmit"
        >
          <el-form-item label="账号" prop="username">
            <el-input
              v-model="form.username"
              :prefix-icon="User"
              placeholder="用户名或邮箱"
              autocomplete="username"
              autofocus
              clearable
            />
          </el-form-item>

          <el-form-item label="密码" prop="password">
            <el-input
              v-model="form.password"
              :prefix-icon="Lock"
              type="password"
              placeholder="请输入密码"
              autocomplete="current-password"
              show-password
            />
          </el-form-item>

          <el-button
            class="login-card__submit"
            type="primary"
            size="large"
            native-type="submit"
            :loading="isLoggingIn"
          >
            登录
            <el-icon v-if="!isLoggingIn" class="el-icon--right"><ArrowRight /></el-icon>
          </el-button>
        </el-form>

        <p class="login-card__hint">
          开发环境测试账号 <code>testuser</code><span>/</span><code>test123</code>
        </p>
      </div>

      <p class="login__copyright">© {{ new Date().getFullYear() }} HR-Agent</p>
    </section>
  </div>
</template>

<style scoped>
.login {
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(440px, 0.95fr);
  min-height: 100vh;
  background: #ffffff;
}

.login__brand {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 44px 56px;
  overflow: hidden;
  color: #ffffff;
  background: linear-gradient(145deg, #0b1220 0%, #102a56 58%, #1d4ed8 140%);
}

.login__brand::before {
  position: absolute;
  top: -18%;
  right: -12%;
  width: 560px;
  height: 560px;
  content: '';
  background: radial-gradient(circle, rgba(96, 165, 250, 0.38) 0%, transparent 68%);
  border-radius: 50%;
}

.login__brand::after {
  position: absolute;
  inset: 0;
  content: '';
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.055) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.055) 1px, transparent 1px);
  background-size: 46px 46px;
  mask-image: linear-gradient(to bottom, rgba(0, 0, 0, 0.7), transparent 78%);
}

.brand,
.brand__content,
.brand__footer {
  position: relative;
  z-index: 1;
}

.brand {
  display: flex;
  gap: 14px;
  align-items: center;
}

.brand-mark {
  box-shadow: 0 10px 24px rgba(2, 8, 23, 0.38);
}

.brand__text {
  display: flex;
  flex-direction: column;
  line-height: 1.25;
}

.brand__text strong {
  font-size: 18px;
  letter-spacing: 0.2px;
}

.brand__text span {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.58);
}

.brand__content {
  max-width: 620px;
  padding: 48px 0;
}

.brand__eyebrow {
  margin-bottom: 20px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 3px;
  color: rgba(147, 197, 253, 0.9);
}

.brand__content h1 {
  font-size: clamp(36px, 4.2vw, 58px);
  font-weight: 700;
  line-height: 1.16;
  letter-spacing: -1.8px;
}

.brand__description {
  max-width: 520px;
  margin-top: 22px;
  font-size: 15px;
  line-height: 1.85;
  color: rgba(255, 255, 255, 0.62);
}

.feature-list {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  padding: 0;
  margin: 38px 0 0;
  list-style: none;
}

.feature {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 16px 14px;
  background: rgba(255, 255, 255, 0.055);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  backdrop-filter: blur(8px);
}

.feature__icon {
  display: grid;
  flex: none;
  place-items: center;
  width: 30px;
  height: 30px;
  font-size: 15px;
  color: #93c5fd;
  background: rgba(59, 130, 246, 0.16);
  border-radius: 9px;
}

.feature span:last-child {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.feature strong {
  font-size: 13px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.92);
}

.feature small {
  font-size: 11px;
  line-height: 1.5;
  color: rgba(255, 255, 255, 0.45);
}

.brand__footer {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.34);
}

.login__panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  background: radial-gradient(circle at 85% 8%, rgba(37, 99, 235, 0.08), transparent 32%), #ffffff;
}

.login-card {
  width: 100%;
  max-width: 420px;
}

.login-card__head {
  margin-bottom: 32px;
}

.login-card__head .brand-mark {
  display: none;
  margin-bottom: 20px;
}

.login-card__head h2 {
  font-size: 30px;
  font-weight: 700;
  letter-spacing: -0.8px;
  color: var(--app-text);
}

.login-card__head p {
  margin-top: 9px;
  font-size: 14px;
  color: var(--app-text-secondary);
}

.login-card :deep(.el-form-item) {
  margin-bottom: 22px;
}

.login-card :deep(.el-form-item__label) {
  padding-bottom: 7px;
  font-size: 13px;
  font-weight: 600;
  color: #334155;
}

.login-card :deep(.el-input__wrapper) {
  padding: 2px 14px;
  background: #f8fafc;
  border-radius: 11px;
  box-shadow: 0 0 0 1px #e2e8f0 inset;
  transition:
    box-shadow 0.2s ease,
    background 0.2s ease;
}

.login-card :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #cbd5e1 inset;
}

.login-card :deep(.el-input__wrapper.is-focus) {
  background: #ffffff;
  box-shadow:
    0 0 0 1px var(--app-primary) inset,
    0 0 0 4px rgba(37, 99, 235, 0.1);
}

.login-card__submit {
  width: 100%;
  height: 46px;
  margin-top: 4px;
  font-weight: 600;
  letter-spacing: 0.4px;
  border-radius: 11px;
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.24);
}

.login-card__hint {
  display: flex;
  gap: 6px;
  align-items: center;
  justify-content: center;
  margin-top: 22px;
  font-size: 12px;
  color: #94a3b8;
}

.login-card__hint code {
  padding: 2px 6px;
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 11px;
  color: #475569;
  background: #f1f5f9;
  border-radius: 5px;
}

.login-card__hint span {
  color: #cbd5e1;
}

.login__copyright {
  display: none;
  margin-top: 40px;
  font-size: 12px;
  color: #94a3b8;
}

@media (max-width: 1080px) {
  .login__brand {
    padding: 36px;
  }

  .feature-list {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .login {
    grid-template-columns: 1fr;
  }

  .login__brand {
    display: none;
  }

  .login__panel {
    min-height: 100vh;
    padding: 28px 22px;
    background:
      radial-gradient(circle at 50% 0%, rgba(37, 99, 235, 0.12), transparent 42%), #ffffff;
  }

  .login-card__head .brand-mark {
    display: grid;
  }

  .login__copyright {
    display: block;
  }
}
</style>
